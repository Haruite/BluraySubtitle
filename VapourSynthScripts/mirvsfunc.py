from typing import Union, Optional, Any
try:
    from collections.abc import Sequence, Mapping
except ImportError:
    from typing import Sequence, Mapping
from functools import partial

import vapoursynth as vs
from vapoursynth import core

__version__ = '0.1.3'
__all__ = [ "RgTools", "GetFrameProp", "SplitPlanes", "RemoveFrameProp", "SetFrameProps", "query_video_format",
            "BM3D", "ToRGB", "ToYUV", "GetMatrix", "ZimgResize",
            "scale_value"
        ]

VSApiVer4 = vs.__api_version__.api_major >= 4
PlanesType = Optional[Union[int, Sequence[int]]]
propType = Any
Format = vs.VideoFormat if VSApiVer4 else vs.Format


######

class RgTools():

    def __init__(self, clip: vs.VideoNode, planes: PlanesType = None) -> None:
        self.clip = clip

        if planes is None:
            self.planes = list(range(clip.format.num_planes))
        elif isinstance(planes, int):
            self.planes = [planes]
        else:
            self.planes = planes

    def _matrix(self, c: str, r: int = 1, m: str = 'pix', mid: bool = False, mlim: int = 0) -> str:
        rc = [i for i in range(-1 * r, r + 1)]
        pn = (r * 2 + 1) ** 2
        pn_h = pn // 2
        
        matrix0 = [f'{c}[{x},{y}] ' for y in rc for x in rc]

        if m == 'pix':
            matrix = matrix0
        
        elif m == 'pixv':
            matrix, i = [], 0
            for y in rc:
                for x in rc:
                    matrix.append(f'{c}[{x},{y}] p{i+1}! ')
                    i += 1

            if mlim == 1:
                matrix += [f'p{pn_h+1}@ p{i+1}@ - abs p{pn_h+1}@ p{pn-i}@ - abs max d{i+1}! ' for i in range(pn_h)]
                matrix += [f'd{i+1}@ ' for i in range(pn_h)]
            elif mlim in [2, 3]:
                matrix += [f'{"y" if mlim==2 else "x"} p{i+1}@ - abs d{i+1}! ' for i in range(pn) if i != pn_h]


        elif m == 'line':
            
            matrix = [f'{matrix0[i]} {matrix0[-(i+1)]} {matrix0[pn_h] if c=="y" and mid else ""} sort{3 if c=="y" and mid else 2} mil{i+1}! {"drop" if c=="y" and mid else ""} mal{i+1}! ' for i in range(pn_h)]
            
            if mlim in [0, 1]:
                matrix += [f'mal{i+1}@ mil{i+1}@ - d{i+1}! 'for i in range(pn_h)]
                matrix += [f'{"y" if mlim==1 else "x"} mil{i+1}@ mal{i+1}@ clip cli{i+1}! 'for i in range(pn_h)]
            elif mlim == [2, 3]:
                matrix += []
        
        elif m == 'line2':
            matrix = [f'{matrix0[i]}{matrix0[-(i+1)]}sort2 mil{i+1}! mal{i+1}! ' for i in range(pn_h)]
            matrix += [f'{c} mil{i+1}@ mal{i+1}@ clip lim{i+1}! ' for i in range(pn_h)]
        
        else:
            raise vs.Error('_matrix mode must in pix, pixv, pixv1, line, line2.')

        if 'pix' in m and  not mid:
            matrix.pop(pn_h)

        return ''.join(matrix)

    def _planes(self, expr) -> Union[str, Sequence[str]]:
        
        if self.planes == list(range(self.clip.format.num_planes)):
            return expr
        else:
            return [(expr if i in self.planes else '') for i in range(self.clip.format.num_planes)]

    def _expr(self, m: int = 1, c: str = 'x', r: int = 1, mid: bool = False, mlim: int = 0) -> Union[str, Sequence[str]]:

        if m not in [4, 19, 20] and r != 1:
            raise vs.Error('RgTools.RemoveGrain: radius > 1 now only support mode (int) = 4 / 19 / 20.')

        if m in range(1, 5):
            rn = (r * 2 + 1) ** 2 - 1 if not mid else (r * 2 + 1) ** 2
            expr = f'{self._matrix(c, r, mid=mid)} sort{rn} dup{rn//2+(4-m) if not mid else rn//2+(4-m)+1} {"y max" if c=="y" and not mid else ""} ma! dup{rn//2-(5-m)} {"y min" if c=="y" and not mid else ""} mi! drop{rn} x mi@ ma@ clip'

        elif m == 5:
            a = f'{self._matrix(c, r, "line", mid=mid, mlim=mlim)}'

            if mlim == 0:
                expr = f'{a}x cli1@ - abs c1! x cli2@ - abs c2! x cli3@ - abs c3! x cli4@ - abs c4! c1@ c2@ c3@ c4@ sort4 mindiff! drop3 mindiff@ c4@ = cli4@ mindiff@ c2@ = cli2@ mindiff@ c3@ = cli3@ cli1@ ? ? ?'
            elif mlim == 1:
                expr = f'{a}y cli1@ - abs c1! y cli2@ - abs c2! y cli3@ - abs c3! y cli4@ - abs c4! c1@ c2@ c3@ c4@ sort4 mindiff! drop3 mindiff@ c4@ = x mil4@ y min mal4@ y max clip mindiff@ c2@ = x mil2@ y min mal2@ y max clip mindiff@ c3@ = x mil3@ y min mal3@ y max clip x mil1@ y min mal1@ y max clip ? ? ?'
            else:
                expr = ''

        elif m == 6:
            a = f'{self._matrix(c, r, "line", mid=mid, mlim=mlim)}'

            if mlim == 0:
                expr = f'{a}x cli1@ - abs 2 * d1@ + c1! x cli2@ - abs 2 * d2@ + c2! x cli3@ - abs 2 * d3@ + c3! x cli4@ - abs 2 * d4@ + c4! c1@ c2@ c3@ c4@ sort4 mindiff! drop3 mindiff@ c4@ = cli4@ mindiff@ c2@ = cli2@ mindiff@ c3@ = cli3@ cli1@ ? ? ?'
            elif mlim == 1:
                expr = f'{a}y cli1@ - abs 2 * d1@ + c1! y cli2@ - abs 2 * d2@ + c2! y cli3@ - abs 2 * d3@ + c3! y cli4@ - abs 2 * d4@ + c4! c1@ c2@ c3@ c4@ sort4 mindiff! drop3 mindiff@ c4@ = x mil4@ y min mal4@ y max clip mindiff@ c2@ = x mil2@ y min mal2@ y max clip mindiff@ c3@ = x mil3@ y min mal3@ y max clip x mil1@ y min mal1@ y max clip ? ? ?'
            else:
                expr = ''

        elif m == 7:
            expr = f'{self._matrix(c, r, "line", mid=mid, mlim=mlim)}x cli1@ - abs d1@ + c1! x cli2@ - abs d2@ + c2! x cli3@ - abs d3@ + c3! x cli4@ - abs d4@ + c4! c1@ c2@ c3@ c4@ sort4 mindiff! drop3 mindiff@ c4@ = cli4@ mindiff@ c2@ = cli2@ mindiff@ c3@ = cli3@ cli1@ ? ? ?'

        elif m == 8:
            expr = f'{self._matrix(c, r, "line", mid=True if c=="y" else False)}x cli1@ - abs d1@ 2 * + c1! x cli2@ - abs d2@ 2 * + c2! x cli3@ - abs d3@ 2 * + c3! x cli4@ - abs d4@ 2 * + c4! c1@ c2@ c3@ c4@ sort4 mindiff! drop3 mindiff@ c4@ = cli4@ mindiff@ c2@ = cli2@ mindiff@ c3@ = cli3@ cli1@ ? ? ?'

        elif m == 9:
            expr = f'{self._matrix(c, r, "line", mid=True if c=="y" else False)}d1@ d2@ d3@ d4@ sort4 mindiff! drop3 mindiff@ d4@ = cli4@ mindiff@ d2@ = cli2@ mindiff@ d3@ = cli3@ cli1@ ? ? ?'

        elif m == 10:
            expr = f'{self._matrix(c, r, "pixv", mid=False if c=="x" else True)}x p1@ - abs d1! x p2@ - abs d2! x p3@ - abs d3! x p4@ - abs d4! {"x p5@ - abs d5!" if c=="y" else ""} x p6@ - abs d6! x p7@ - abs d7! x p8@ - abs d8! x p9@ - abs d9! d1@ d2@ d3@ d4@ {"d5@" if c=="y" else ""} d6@ d7@ d8@ d9@ sort{9 if c=="y" else 8} mindiff! drop{8 if c=="y" else 7} mindiff@ d8@ = p8@ mindiff@ d9@ = p9@ mindiff@ d7@ = p7@ mindiff@ d2@ = p2@ mindiff@ d3@ = p3@ mindiff@ d1@ = p1@ mindiff@ d6@ = p6@ {"mindiff@ d5@ = p5@" if c=="y" else ""} p4@ ? ? ? ? ? ? ? {"?" if c=="y" else ""}'

        elif m in [11, 12]:
            expr = f'{self._matrix(c, r, "pixv", True)}p5@ 4 * p2@ p4@ p6@ p8@ + + + 2 * + p1@ p3@ p7@ p9@ + + + + 16 /'

        elif m in [13, 14]:
            expr = f'{self._matrix(c, r, "pixv")}p1@ p9@ - abs d1! p2@ p8@ - abs d2! p3@ p7@ - abs d3! d1@ d2@ d3@ sort3 mindiff! drop2 Y 2 % {0 if m==13 else 1} = mindiff@ d2@ = p2@ p8@ 1 + + 2 / mindiff@ d3@ = p3@ p7@ 1 + + 2 / p1@ p9@ 1 + + 2 / ? ? x ?'

        elif m in [15, 16]:
            expr = f'{self._matrix(c, r, "pixv")}p1@ p9@ - abs d1! p2@ p8@ - abs d2! p3@ p7@ - abs d3! d1@ d2@ d3@ sort3 mindiff! drop2 p2@ p8@ + 2 * p1@ p3@ p7@ p9@ 4 + + + + + 8 / average! Y 2 % {0 if m==15 else 1} = mindiff@ d2@ = average@ p2@ p8@ sort2 swap1 clip mindiff@ d3@ = average@ p3@ p7@ sort2 swap1 clip x average@ p1@ p9@ sort2 swap1 clip x ? ? ? x ?'
            
        elif m == 17:
            expr = f'{self._matrix(c, r, "line", mid=mid)}mil1@ mil2@ mil3@ mil4@ sort4 swap3 dup lower! drop4 mal1@ mal2@ mal3@ mal4@ sort4 dup upper! drop4 lower@ upper@ sort2 mi0! ma0! {"mi0@ y min mi0! ma0@ y max ma0! " if c=="y" else ""}x mi0@ ma0@ clip'

        elif m == 18:
            a = "sort2 swap" if c == "x" else "p5@ sort3 swap drop swap"
            expr = f'{self._matrix(c, r, "pixv", True, True)}sort4 mindiff! drop3 mindiff@ d4@ = x p4@ p6@ {a} clip mindiff@ d2@ = x p2@ p8@ {a} clip mindiff@ d3@ = x p3@ p7@ {a} clip x p1@ p9@ {a} clip ? ? ?'

        elif m in [19, 20] and c == "x":
            pn = (r * 2 + 1) ** 2 - 1 if m == 19 else (r * 2 + 1) ** 2
            expr = f'{self._matrix(c, r, "pix", False if m==19 else True)}{"+ " * (pn - 1)}{pn} /'

        elif m == 21 and c == "x":
            expr = f'{self._matrix(c, r, "pixv")}p1@ p9@ + m1! p2@ p8@ + m2! p3@ p7@ + m3! p4@ p6@ + m4! m1@ 2 / l1l! m2@ 2 / l2l! m3@ 2 / l3l! m4@ 2 / l4l! m1@ 1 + 2 / l1h! m2@ 1 + 2 / l2h! m3@ 1 + 2 / l3h! m4@ 1 + 2 / l4h! l1l@ l2l@ l3l@ l4l@ sort4 mi! drop3 l1h@ l2h@ l3h@ l4h@ sort4 dup3 ma! drop4 x mi@ ma@ clip'

        elif m == 22 and c == "x":
            expr = f'{self._matrix(c, r, "pixv")}p1@ p9@ + 2 / s1! p4@ p6@ + 2 / s2! p7@ p3@ + 2 / s3! p8@ p2@ + 2 / s4! s1@ s2@ s3@ s4@ sort4 mi! drop3 s1@ s2@ s3@ s4@ sort4 dup3 ma! drop4 x mi@ ma@ clip'

        elif m == 23 and c == "x":
            expr = f'{self._matrix(c, r, "line")}x mal1@ - d1@ min x mal2@ - d2@ min x mal3@ - d3@ min x mal4@ - d4@ min sort4 dup3 0 max u! drop4 mil1@ x - d1@ min mil2@ x - d2@ min mil3@ x - d3@ min mil4@ x - d4@ min sort4 dup3 0 max d! drop4 x u@ - d@ +'

        elif m == 24 and c == "x":
            expr = f'{self._matrix(c, r, "line")}x mal1@ - tu1! x mal2@ - tu2! x mal3@ - tu3! x mal4@ - tu4! tu1@ d1@ tu1@ - min tu2@ d2@ tu2@ - min tu3@ d3@ tu3@ - min tu4@ d4@ tu4@ - min sort4 dup3 0 max u! drop4 mil1@ x - td1! mil2@ x - td2! mil3@ x - td3! mil4@ x - td4! td1@ d1@ td1@ - min td2@ d2@ td2@ - min td3@ d3@ td3@ - min td4@ d4@ td4@ - min sort4 dup3 0 max d! drop4 x u@ - d@ +'

        elif m in [19, 22] and c == "y":
            expr = f'{self._matrix(c, r, "pixv", mid, mlim)}d1@ d2@ d3@ d4@ d6@ d7@ d8@ d9@ sort8 dup mindiff! drop8 {"x" if m==19 else "y"} {"y" if m==19 else "x"} mindiff@ - 0 0xFFFF clip {"y" if m==19 else "x"} mindiff@ + 0 0xFFFF clip clip'
        
        elif m in [20, 23] and c == "y":
            expr = f'{self._matrix(c, r, "pixv", mid, mlim)}d1@ d2@ sort2 mindiff! maxdiff! '
            for i in range(3, 9):
                if i != 5:
                    expr += f'maxdiff@ mindiff@ d{i}@ clip maxdiff! mindiff@ d{i}@ min mindiff! '
            expr += f'maxdiff@ mindiff@ d9@ clip maxdiff! {"x" if m==20 else "y"} {"y" if m==20 else "x"} maxdiff@ - 0 0xFFFF clip {"y" if m==20 else "x"} maxdiff@ + 0 0xFFFF clip clip'

        elif m in [21, 24] and c == "y":
            expr = f'{self._matrix(c, r, "line", mid, mlim)}'
            for i in range(1, 5):
                expr += f'mal{i}@ {"y" if m==21 else "x"} - 0 0xFFFF clip d{i}! '
            for i in range(1, 5):
                expr += f'{"y" if m==21 else "x"} mil{i}@ - 0 0xFFFF clip rd{i}! '
            for i in range(1, 5):
                expr += f'd{i}@ rd{i}@ max '
            expr += f'sort4 dup u! drop4 {"x" if m==21 else "y"} {"y" if m==21 else "x"} u@ - 0 0xFFFF clip {"y" if m==21 else "x"} u@ + 0 0xFFFF clip clip'

        else:
            expr = ''

        return self._planes(expr)

    def RemoveGrain(self, mode: Union[int, str, float], radius: int = 1) -> vs.VideoNode:
        '''
        mode:
            0: None;
            int (1-24): same as Rgtools / rgvs.RemoveGrain;
            float (1.0, 1.58, 2.25, 2.75, 4.0): same as Avisynth blur();
            string (Median):
                Median: same as std.Median, ctmf.CTMF;
                Box: same as box.Blur(hradius = vradius = radius), std.BoxBlur()
        radius:
            Now only support mode in [4 (median), 19, 20 (box), 1.58, 2.75, 4.0].
        '''
        if isinstance(mode, int):
            if mode == 0:
                last = self.clip
            elif mode in range(1, 25):
                last = self.clip.akarin.Expr(self._expr(mode, r=radius))
            else:
                raise vs.Error('RgTools.RemoveGrain() now only support mode (int) 0-24.')

        elif isinstance(mode, float):
            if mode == 1.0:
                last = self.clip.akarin.Expr(self._expr(11, r=radius))
            elif mode == 1.58:
                last = self.clip.akarin.Expr(self._expr(20, r=radius))
            elif mode == 2.25:
                last = self.clip.akarin.Expr(self._expr(11, r=radius)).akarin.Expr(self._expr(20, r=radius))
            elif mode == 2.75:
                last = self.clip.akarin.Expr(self._expr(20, r=radius)).akarin.Expr(self._expr(20, r=radius))
            elif mode == 4.0:
                last = self.clip.akarin.Expr(self._expr(11, r=radius)).akarin.Expr(self._expr(20, r=radius)).akarin.Expr(self._expr(20, r=radius))
            else:
                raise vs.Error('RgTools.RemoveGrain() now only support mode (float) 1.0 / 1.58 / 2.25 / 2.75 / 4.0.')

        elif isinstance(mode, str):
            mode = mode.lower()
            if mode == 'median':
                last = self.clip.akarin.Expr(self._expr(4, r=radius))
            elif mode == 'box':
                last = self.clip.akarin.Expr(self._expr(20, r=radius))
            else:
                raise vs.Error('RgTools.RemoveGrain() now only support mode (string) “Median”.')

        else:
            raise vs.Error('RgTools.RemoveGrain() mode now only support int / float / string.')

        return last

    def Repair(self, repclip: vs.VideoNode, mode: int) -> vs.VideoNode:
        '''
        mode:
            same as Rgtools / rgvs.Repair, now only support 1-24
        '''
        mid = False

        if mode in range(1, 11):
            mid = True
            mlim = 0
        elif mode in range(11, 17):
            mode = mode - 10
            mlim = 1
        elif mode in [17, 18]:
            mlim = 0
        elif mode in range(19, 22):
            mlim = 2
        elif mode in range(22, 25):
            mlim = 3
        else:
            raise vs.Error('RgTools.Repair() mode now only support 1-24.')

        return core.akarin.Expr([self.clip, repclip], self._expr(mode, 'y', mid=mid, mlim=mlim))

    # def TemporalRepair(self)

    def Clense(self, prev: Optional[vs.VideoNode] = None, next: Optional[vs.VideoNode] = None) -> vs.VideoNode:
        '''A temporal median of three frames (previous, current and next).'''
        
        prev = self.clip if prev is None else prev
        next = self.clip if next is None else next
        prev = prev[0] + prev[:-1]
        next = next[1:] + next[-1]
        return core.akarin.Expr([self.clip, prev, next], self._planes('x y z sort3 dup1 mid! drop3 mid@'))

    def VerticalCleaner(self, mode: int):
        '''
        VerticalCleaner is a fast vertical median filter.
        mode:
            same as Rgtools / rgvs.VerticalCleaner, support 0-2
        '''
        if mode == 0:
            last = self.clip
        elif mode == 1:
            # x x[0,-1] x[0,1] sort3 mi! drop ma! x mi@ ma@ clip
            last = core.akarin.Expr(self.clip, self._planes('x[0,-1] x[0,1] sort2 mi! ma! x mi@ ma@ clip')) 
        elif mode == 2:
            # Thanks Dogway
            last = core.akarin.Expr(self.clip, self._planes('x[0,-2] b2! x[0,-1] b1! x[0,1] t1! x[0,2] t2! b1@ b2@ - b1@ + t1@ t2@ - t1@ + min b1@ max t1@ max b1@ b2@ b1@ - - t1@ t2@ t1@ - - max b1@ t1@ min min x swap2 clip'))
        else:
            raise vs.Error('RgTools.VerticalCleaner() mode only have 0-2.')

        return last


def GetFrameProp(input: vs.VideoNode, prop: str, frame_num: int = 0) -> propType:
    return input.get_frame(frame_num).props[prop]


def SplitPlanes(input: vs.VideoNode, rm_prop: bool=False, prop: propType = '_Matrix') -> Union[Sequence[vs.VideoNode], vs.VideoNode]:
    '''Same as API4 std.SplitPlanes. But you can use `rm_prop` and `prop` remove useless props.'''
    v_list = core.std.SplitPlanes(input) if VSApiVer4 else [core.std.ShufflePlanes(input, x, vs.GRAY) for x in range(input.format.num_planes)]
    return [RemoveFrameProp(x, prop) for x in v_list] if input.format.color_family == vs.RGB and rm_prop else v_list


def RemoveFrameProp(input: vs.VideoNode, prop: propType) -> vs.VideoNode:
    '''Helper of function SetFrameProps.'''
    return core.std.RemoveFrameProps(input, prop) if VSApiVer4 else core.std.SetFrameProp(input, prop=prop, delete = True)


def SetFrameProps(input: vs.VideoNode, props: Union[propType, Sequence[propType]] = None, prop_src: Optional[vs.VideoNode] = None, delete: bool = False, show: bool = False) -> vs.VideoNode:
    '''Wrapper of API3’s std.SetFrameProp; API4’s std.SetFrameProps, std.RemoveFrameProps and std.CopyFrameProps.'''
    funcName = 'SetFrameProps'
    # how delete all in api3 and delete from ref clip.
    if isinstance(props, str) and prop_src is None:
        prop = props
        if delete: res = RemoveFrameProp(input, prop)
        else: raise vs.Error(f'{funcName}: “props” should be dict when delete=False.')

    elif isinstance(props, list) and prop_src is None:
        if delete:
            res = input
            for prop in props: res = RemoveFrameProp(res, prop)
        else: raise vs.Error(f'{funcName}: “props” should be dict when delete=False.')

    elif isinstance(props, dict) and prop_src is None:
        propL = list(props.keys())
        
        if delete:
            res = input
            for prop in propL: res = RemoveFrameProp(res, prop)
        else:
            if VSApiVer4:
                res = core.std.SetFrameProps(input, **props)
            else:
                res = input
                
                for prop in propL:

                    val = props[prop]
                    if isinstance(val, float): valD = dict(floatval = val)
                    elif isinstance(val, int): valD = dict(intval = val)
                    elif isinstance(val, str): valD = dict(data = val)
                    else: raise vs.Error(f'{funcName}: val should be int, float or string when props is dict.')

                    res:vs.VideoNode = res.std.SetFrameProp(prop, **valD)

    elif prop_src is not None:
        delete = False
        if VSApiVer4:
            res = core.std.CopyFrameProps(input, prop_src)
        else: raise vs.Error(f'{funcName}: Now api3 don’t support this mode.')

    else: res = input

    return res.text.FrameProps() if show else res


def query_video_format(color_family: vs.ColorFamily, sample_type: vs.SampleType, bits_per_sample: int, subsampling_w: int = 0, subsampling_h: int = 0) -> Format:
    register_format = partial(core.query_video_format if VSApiVer4 else core.register_format)
    return register_format(color_family, sample_type, bits_per_sample, subsampling_w, subsampling_h)


######

# https://github.com/WolframRhodium/VapourSynth-BM3DCUDA
def BM3D(clip: vs.VideoNode, ref: Optional[vs.VideoNode] = None, sigma: Union[int, float, Sequence[Union[int, float]]] = [3.0, 3.0, 3.0], block_step: int = 8, bm_range: int = 9, radius: int = 0, ps_num: int = 2, ps_range: int = 4, chroma: bool = False, device_id: Optional[int] = None, fast: Optional[bool] = None, extractor_exp: Optional[int] = None, device_type: str = 'cpu', opp: bool = False) -> vs.VideoNode:
    '''BM3DCUDA wrapper function.\n
        If sigma is int or float, will only process first plane.\n
        device_type:
            cpu - bm3dcpu, gpu / cuda - bm3dcuda, cuda_rtc: bm3dcuda_rtc
        opp:
            if clip and ref is OPP, you should opp = True.
    '''
    funcName = 'BM3D'
    bm3d_plugin = {
        "cpu": core.bm3dcpu if hasattr(core, 'bm3dcpu') else None,
        "gpu": core.bm3dcuda if hasattr(core, 'bm3dcuda') else None,
        "cuda": core.bm3dcuda if hasattr(core, 'bm3dcuda') else None,
        "cuda_rtc": core.bm3dcuda_rtc if hasattr(core, 'bm3dcuda_rtc') else None
    }

    sFormat = clip.format
    sColorFamily = sFormat.color_family
    sbitPS = sFormat.bits_per_sample
    sSType = sFormat.sample_type
    sPlaneN = sFormat.num_planes

    cpu = True if device_type == 'cpu' else False

    bm3d_v2 = True if hasattr(bm3d_plugin[device_type], 'BM3Dv2') else False
    bm3d_args = dict(sigma=sigma, block_step=block_step, bm_range=bm_range, radius=radius, ps_num=ps_num, ps_range=ps_range, chroma=chroma)

    if device_type in bm3d_plugin.keys():
        BM3Dc = bm3d_plugin[device_type].BM3Dv2 if (radius > 0 and bm3d_v2) else bm3d_plugin[device_type].BM3D
        BM3Da = partial(BM3Dc, **bm3d_args, device_id=device_id, fast=fast, extractor_exp=extractor_exp) if not cpu else partial(BM3Dc, **bm3d_args)
    else:
        raise vs.Error('BM3D: device_type only support cpu, gpu, cuda, cuda_rtc.')

    if isinstance(ref, vs.VideoNode):
        if ref.format != sFormat:
            raise vs.Error(f'{funcName}: clip.format != ref.format.')

    if isinstance(sigma, (int, float)):
        sigma = [sigma, 0, 0]
    
    if isinstance(sigma, list):
        if len(sigma) < sPlaneN:
            sigma.extend([sigma[-1]] * (sPlaneN - len(sigma)))

    pre_ref = None
    if sPlaneN == 1 or opp or sColorFamily == vs.RGB:
        pre = clip
        if isinstance(ref, vs.VideoNode):
            pre_ref = ref
    elif sColorFamily == vs.YUV:
        if sigma[1] == sigma[2] == 0:
            pre = clip.std.ShufflePlanes(0, vs.GRAY)
            if isinstance(ref, vs.VideoNode):
                pre_ref = ref.std.ShufflePlanes(0, vs.GRAY)
        else:
            pre = ToRGB(clip)
            if isinstance(ref, vs.VideoNode):
                pre_ref = ToRGB(ref)
    else:
        raise vs.Error(f'{funcName}: clip, ref must be GRAY, OPP, RGB or YUV. You must opp = True if you use OPP input clip.')

    if pre.format.bits_per_sample != 32:
        pre = pre.fmtc.bitdepth(bits=32)
        if isinstance(ref, vs.VideoNode):
            pre_ref = ref.fmtc.bitdepth(bits=32)

    flt = BM3Da(pre, ref = pre_ref)

    if radius > 0 and not bm3d_v2:
        flt = SetFrameProps(flt, {"BM3D_V_radius": radius, "BM3D_V_process": [s > 0 for s in sigma]}).bm3d.VAggregate(radius=radius, sample=1)

    if sColorFamily == vs.YUV and not opp:
        if sigma[1] == sigma[2] == 0:
            flt = core.std.ShufflePlanes([flt, clip], [0,1,2], vs.YUV)
        else:
            flt = ToYUV(flt)

    if flt.format.bits_per_sample != sbitPS:
        flt = flt.fmtc.bitdepth(bits=sbitPS, dmode=1)

    return flt


def ToRGB(clip: vs.VideoNode, kernel: str = "bicubic", a1: float = 0, a2: float = 0.5, useZ: bool = False, matrix: Union[str, int] = None) -> vs.VideoNode:
    '''Convert 8-16 bit TVRange SDR YUV420 to 32bit float full-range RGB'''
    funcName = 'ToRGB'
    
    sFormat = clip.format
    sColorFamily = sFormat.color_family

    if sColorFamily != vs.YUV:
        raise vs.Error(f'{funcName}: Only support YUV input.')
    
    matrixI, matrixS = GetMatrix(clip, matrix)

    if useZ:
        # dFormat = query_video_format(vs.RGB, vs.FLOAT, 32, 0, 0)
        last = ZimgResize(clip, kernel=kernel, a = a1, b = a2, format = vs.RGBS)
    else:
        last = clip.fmtc.resample(kernel = kernel, a1 = a1, a2 = a2, css = "444", planes = [2,3,3], fulls = False, fulld = False)
        last = last.fmtc.matrix(fulls = False, fulld = True, mat = matrixS, col_fam=vs.RGB).fmtc.bitdepth(bits=32)

    return last


def ToYUV(clip: vs.VideoNode, kernel: str = "bicubic", a1: float = 0, a2: float = 0.5, useZ: bool = False, matrix: Union[str, int] = None, css: str = "420") -> vs.VideoNode:
    '''Convert 32bit float full-range RGB to 16 bit TVRange SDR YUV420.'''
    funcName = 'ToYUV'
    
    sFormat = clip.format
    sColorFamily = sFormat.color_family

    if sColorFamily != vs.RGB:
        raise vs.Error(f'{funcName}: Only support RGB input.')

    matrixI, matrixS = GetMatrix(clip, matrix)

    if useZ:
        last = ZimgResize(clip, kernel=kernel, a = a1, b = a2, format = vs.YUV420P16 if css == "420" else vs.YUV444P16, matrix = matrixI)
    else:
        last = clip.fmtc.bitdepth(bits=16, dmode = 1).fmtc.matrix(fulls = True, fulld = False, mat = matrixS, col_fam=vs.YUV)
        last = last.fmtc.resample(kernel = kernel, a1 = a1, a2 = a2, css = css)

    return last


def GetMatrix(input: vs.VideoNode, matrix: Optional[Union[str, int]] = None, dIsRGB: Optional[bool] = None) -> Sequence:
    '''Helper to get Matrix.'''
    funcName = 'GetMatrix'

    matrixD = {
    # ITU-T H.265 Table E.5
      "0": "RGB",         # GBR, YZX (XYZ)
      "1": "709",         # bt709
      "2": "Unspecified", # Unspecified
      "4": "FCC",         # fcc
      "5": "601",         # bt470bg
      "6": "601",         # smpte170m
      "7": "240",         # smpte240m
      "8": "YCgCo",       # YCgCo
      "9": "2020",        # bt2020nc
     "10": "2020cl",      # bt2020c
    "100": "OPP"          # opponent color space
    }
    
    sFormat = input.format
    sColorFamily = sFormat.color_family
    sIsRGB = sColorFamily == vs.RGB

    if dIsRGB is None: dIsRGB = not sIsRGB

    SD, HD, UHD = False, False, False
    if input.width <= 1024 and input.height <= 576: SD = True
    elif input.width <= 2048 and input.height <= 1536: HD = True
    else: UHD = True

    if matrix is None: matrix = "Unspecified"
    if matrix == 2 or matrix == "Unspecified":
        if dIsRGB and sIsRGB: matrix = "RGB"
        else: matrix = "601" if SD else "2020" if UHD else "709"

    matrixIL = list(matrixD.keys())
    matrixSL = list(matrixD.values())

    if matrix in matrixIL:
        matrixI, matrixS = matrix, matrixD[matrix]
    elif matrix in matrixSL:
        matrixI, matrixS = matrixIL[matrixSL.index(matrix)], matrix
    else: raise ValueError(f'{funcName}: “matrix” shoule in {matrixIL} + {matrixSL}.')
    matrixI = int(matrixI)

    return [matrixI, matrixS]


def ZimgResize(input: vs.VideoNode, w: Optional[int] = None, h: Optional[int] = None, sx: float = 0.0, sy: float = 0.0, kernel: str = "spline", a: Optional[Union[float, int]] = None, b: Union[float, int] = 0.5, format: Optional[int] = None, matrix: Optional[int] = None, ex_args: Mapping[str, Any] = {}) -> vs.VideoNode:
    '''Simple wrapper of zimg resize'''
    funcName = 'ZimgResize'

    if w is None: w = input.width
    if h is None: h = input.height
    
    kernel = kernel.lower()

    kernelL = [
        "point", "linear", "bilinear", "triangle",
        "cubic", "bicubic", "hermite", "bspline", "catmull_rom", "mitchell", "robidoux", "robidouxsharp", "robidouxsoft", "ps_bicubic", "softbicubic",
        "lanczos", "spline", "spline16", "spline36", "spline64"  # default spline36
    ]

    if a is None:
        if kernel == "spline": a = 3
        elif kernel == "lanczos": a = 4
        else: a = 0

    z_args = dict(width = w, height = h, format = format, matrix = matrix, src_left = sx, src_top = sy, **ex_args)

    if kernel == "point":
        res = input.resize.Point(**z_args)

    elif kernel in ["linear", "bilinear", "triangle"]:
        res = input.resize.Bilinear(**z_args)

    elif kernel in ["cubic", "bicubic", "hermite", "bspline", "catmull_rom", "mitchell", "robidoux", "robidouxsharp", "robidouxsoft", "ps_bicubic", "softbicubic"]:
        if kernel == "hermite": bcargs = [0, 0]
        elif kernel == "bspline": bcargs = [1, 0]
        elif kernel == "catmull_rom": bcargs = [0, 1/2]
        elif kernel == "mitchell": bcargs = [1/3, 1/3]
        elif kernel == "robidoux": bcargs = [0.3782, 0.3109]
        elif kernel == "robidouxsharp": bcargs = [0.2620, 0.3690]
        elif kernel == "robidouxsoft": bcargs = [0.6796, 0.1602]
        elif kernel == "ps_bicubic": bcargs = [0, 0.75]
        elif kernel == "softbicubic":
            if 50 <= a <= 100:
                a = a / 100
            elif 0.5 <= a <= 1.0:
                a = a
            else:
                raise vs.Error(f'{funcName}: a should between (0.5 and 1.0) or (50 and 100).') # softcubic: bicubic, b+c=1 and b>=0.5
            bcargs = [a, 1 - a]
        else: bcargs = [a, b]

        res = input.resize.Bicubic(**z_args, filter_param_a=bcargs[0], filter_param_b=bcargs[1])

    elif kernel == "lanczos":
        res = input.resize.Lanczos(**z_args, filter_param_a=int(a))

    elif (kernel == "spline" and int(a) == 2) or kernel == "spline16":
        res = input.resize.Spline16(**z_args)

    elif (kernel == "spline" and int(a) == 3) or kernel == "spline36":
        res = input.resize.Spline36(**z_args)

    elif (kernel == "spline" and int(a) == 4) or kernel == "spline64":
        res = input.resize.Spline64(**z_args)
    
    else: raise vs.Error(f'{funcName}: “kenel” only support in {kernelL}.')

    return res


###### From vsutil

def scale_value(value: Union[int, float], input_depth: int, output_depth: int, range_in: int = 0, range: Optional[int] = None, scale_offsets: bool = False, chroma: bool = False) -> Union[int, float]:
    """
    Scales a given value between bit depths, sample types, and / or ranges.

    input_depth, output_depth:  Bit depth of the "value" parameter
    range_in, range: Pixel range of the input / output “value”. No clamping is performed. 0 limited, 1 full.
    scale_offsets:  Whether or not to apply YUV offsets to float chroma and/or TV range integer values.
                    e.g. when scaling a TV range value of 16 to float, setting this to True will return “0.0” rather than “0.073059…”
    chroma:    Whether or not to treat values as chroma instead of luma

    >>> scale_value(16, 8, 32, range_in=0)
    0.0730593607305936
    >>> scale_value(16, 8, 32, range_in=0, scale_offsets=True)
    0.0
    >>> scale_value(16, 8, 32, range_in=0, scale_offsets=True, chroma=True)
    -0.5
    """

    range_in = 1 if input_depth == 32 else range_in
    range = 1 if output_depth == 32 else range

    def peak_pixel_value(bits: int, range_: Optional[int], chroma_: bool) -> int:
        if bits == 32:
            return 1
        if range_:
            return (1 << bits) - 1
        return (224 if chroma_ else 219) << (bits - 8)

    input_peak  = peak_pixel_value(input_depth,  range_in,  chroma)
    output_peak = peak_pixel_value(output_depth, range, chroma)

    if input_depth == output_depth and range_in == range:
        return value

    if scale_offsets:
        if output_depth == 32 and chroma:
            value -= 128 << (input_depth - 8)
        elif range and not range_in:
            value -= 16 << (input_depth - 8)

    value *= output_peak / input_peak

    if scale_offsets:
        if input_depth == 32 and chroma:
            value += 128 << output_depth - 8
        elif range_in and not range:
            value += 16 << (output_depth - 8)

    return value