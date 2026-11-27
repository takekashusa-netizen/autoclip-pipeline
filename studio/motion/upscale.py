"""Torch-free anime upscaler: loads Real-ESRGAN (RRDBNet x4 anime_6B, BSD-3) weights straight from the
.pth zip with a tiny unpickler, rebuilds the network as an ONNX graph, runs it on onnxruntime (CPU)."""
import io, os, pickle, zipfile, collections
import numpy as np

def load_pth(path):
    zf = zipfile.ZipFile(path); names = zf.namelist()
    root = names[0].split('/')[0]
    class Storage:
        def __init__(self, dtype): self.dtype = dtype
    DT = {'FloatStorage': np.float32, 'HalfStorage': np.float16, 'LongStorage': np.int64, 'IntStorage': np.int32, 'DoubleStorage': np.float64}
    def rebuild(storage, offset, size, stride, *a, **k):
        arr = storage
        n = int(np.prod(size)) if len(size) else 1
        if not len(size): return arr[offset:offset + 1].reshape(())
        st = np.array(stride) * arr.itemsize
        return np.lib.stride_tricks.as_strided(arr[offset:], shape=tuple(size), strides=tuple(st)).copy()
    class U(pickle.Unpickler):
        def find_class(self, mod, name):
            if mod.startswith('torch') and name == '_rebuild_tensor_v2': return rebuild
            if mod.startswith('torch') and name in DT: return Storage(DT[name])
            if mod == 'collections' and name == 'OrderedDict': return collections.OrderedDict
            if mod.startswith('torch') and name == '_rebuild_parameter': return lambda d, rg, bh: d
            return super().find_class(mod, name)
        def persistent_load(self, pid):
            _, stype, key, loc, numel = pid
            dt = stype.dtype if isinstance(stype, Storage) else np.float32
            return np.frombuffer(zf.read(f'{root}/data/{key}'), dtype=dt)
    obj = U(io.BytesIO(zf.read(f'{root}/data.pkl'))).load()
    return obj.get('params_ema', obj.get('params', obj))

def build_onnx(sd, path):
    import onnx
    from onnx import helper, TensorProto, numpy_helper
    nodes, inits = [], []; c = [0]
    def nm(p): c[0] += 1; return f'{p}{c[0]}'
    def conv(x, key, act=True):
        w, b = sd[key + '.weight'], sd[key + '.bias']
        inits.append(numpy_helper.from_array(w.astype(np.float32), key + '.w')); inits.append(numpy_helper.from_array(b.astype(np.float32), key + '.b'))
        y = nm('c'); nodes.append(helper.make_node('Conv', [x, key + '.w', key + '.b'], [y], pads=[1, 1, 1, 1], kernel_shape=[3, 3]))
        if act:
            z = nm('a'); nodes.append(helper.make_node('LeakyRelu', [y], [z], alpha=0.2)); return z
        return y
    def const(v):
        n_ = nm('k'); inits.append(numpy_helper.from_array(np.array(v, np.float32), n_)); return n_
    def add(a, b): y = nm('add'); nodes.append(helper.make_node('Add', [a, b], [y])); return y
    def mul(a, k): y = nm('mul'); nodes.append(helper.make_node('Mul', [a, const(k)], [y])); return y
    def cat(xs): y = nm('cat'); nodes.append(helper.make_node('Concat', xs, [y], axis=1)); return y
    def up(x):
        y = nm('up'); nodes.append(helper.make_node('Resize', [x, '', const([1, 1, 2, 2])], [y], mode='nearest')); return y
    nb = len({k.split('.')[1] for k in sd if k.startswith('body.')})
    x = 'input'; feat = conv(x, 'conv_first', act=False); b = feat
    for i in range(nb):
        r_in = b
        for r in (1, 2, 3):
            p = f'body.{i}.rdb{r}'; x0 = r_in
            x1 = conv(x0, p + '.conv1'); x2 = conv(cat([x0, x1]), p + '.conv2'); x3 = conv(cat([x0, x1, x2]), p + '.conv3')
            x4 = conv(cat([x0, x1, x2, x3]), p + '.conv4'); x5 = conv(cat([x0, x1, x2, x3, x4]), p + '.conv5', act=False)
            r_in = add(mul(x5, 0.2), x0)
        b = add(mul(r_in, 0.2), b)
    body = conv(b, 'conv_body', act=False); feat = add(feat, body)
    feat = conv(up(feat), 'conv_up1'); feat = conv(up(feat), 'conv_up2')
    out = conv(conv(feat, 'conv_hr'), 'conv_last', act=False)
    nodes.append(helper.make_node('Identity', [out], ['output']))
    g = helper.make_graph(nodes, 'rrdbnet', [helper.make_tensor_value_info('input', TensorProto.FLOAT, [1, 3, None, None])],
                          [helper.make_tensor_value_info('output', TensorProto.FLOAT, [1, 3, None, None])], inits)
    m = helper.make_model(g, opset_imports=[helper.make_opsetid('', 13)]); m.ir_version = 8
    onnx.save(m, path)

_SESS = {}
def session(pth):
    import onnxruntime as ort
    onx = os.path.splitext(pth)[0] + '.onnx'
    if not os.path.exists(onx): build_onnx(load_pth(pth), onx)
    if onx not in _SESS:
        so = ort.SessionOptions(); so.intra_op_num_threads = os.cpu_count() or 2
        _SESS[onx] = ort.InferenceSession(onx, so, providers=['CPUExecutionProvider'])
    return _SESS[onx]

def upscale_rgba(img, pth=None, tile=192, pad=12):
    """PIL RGBA/RGB -> 4x PIL image. Colour through the network (tiled), alpha with Lanczos."""
    from PIL import Image
    if pth is None:
        import config; pth = config.model('anime_x4.pth')
    s = session(pth)
    rgb = np.asarray(img.convert('RGB'), np.float32) / 255.0
    h, w = rgb.shape[:2]; out = np.zeros((h * 4, w * 4, 3), np.float32)
    for y0 in range(0, h, tile):
        for x0 in range(0, w, tile):
            ya, xa = max(0, y0 - pad), max(0, x0 - pad); yb, xb = min(h, y0 + tile + pad), min(w, x0 + tile + pad)
            t = rgb[ya:yb, xa:xb].transpose(2, 0, 1)[None]
            r = s.run(None, {'input': t})[0][0].transpose(1, 2, 0)
            oy, ox = (y0 - ya) * 4, (x0 - xa) * 4; th, tw = min(tile, h - y0) * 4, min(tile, w - x0) * 4
            out[y0 * 4:y0 * 4 + th, x0 * 4:x0 * 4 + tw] = r[oy:oy + th, ox:ox + tw]
    res = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))
    if img.mode == 'RGBA':
        res.putalpha(img.getchannel('A').resize(res.size, Image.LANCZOS))
    return res
