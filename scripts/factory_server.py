"""Portable factory data, render plans, local execution and Slurm submission."""
import argparse
import json
from pathlib import Path

from robofrontier.factory import bundle
from robofrontier.factory import server


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    export=sub.add_parser('export',help='Maintainer: freeze portable data from existing source records')
    for name in ('scene','release','cameras','asset','output','source-root'):
        export.add_argument('--'+name,type=Path,required=True)
    pack=sub.add_parser('pack',help='Maintainer: verify and archive a portable data directory')
    pack.add_argument('--data-root',type=Path,required=True);pack.add_argument('--output',type=Path,required=True)
    setup=sub.add_parser('setup',help='Download and verify the pinned factory data release')
    setup.add_argument('--config',type=Path,default=server.ROOT/'configs/factory-assets.json')
    setup.add_argument('--data-root',type=Path,default=server.ROOT/'runs/factory-data/r14')
    setup.add_argument('--archive',type=Path)
    imported=sub.add_parser('import-motion',help='Compose a factory for one closed benchmark motion recording')
    imported.add_argument('--data-root',type=Path,default=server.ROOT/'runs/factory-data/r14')
    imported.add_argument('--recording',type=Path,required=True);imported.add_argument('--output',type=Path,required=True)
    imported.add_argument('--speedup',type=float,help="Playback speedup; omit for the family's release speedup")
    imported.add_argument('--keep-idle',action='store_true',help='Keep every recorded state (an all-retained edit)')
    imported.add_argument('--timeline',type=Path,help='Motion edit to follow, such as a checked motion-cut.json')
    project=sub.add_parser('project',help='Create an editable English full-tour project')
    project.add_argument('--data-root',type=Path,default=server.ROOT/'runs/factory-data/r14')
    project.add_argument('--output',type=Path,required=True)
    edit=sub.add_parser('edit-video',help='Text-only post-production; preserve source movie')
    edit.add_argument('--project',type=Path,required=True);edit.add_argument('--input',type=Path,required=True)
    edit.add_argument('--output',type=Path,required=True)
    for name in ('verify','doctor','prepare'):
        a=sub.add_parser(name)
        a.add_argument('--data-root',type=Path,default=server.ROOT/'runs/factory-data/r14')
        if name=='doctor':a.add_argument('--blender');a.add_argument('--device',choices=('METAL','OPTIX','CUDA','CPU'))
        if name=='prepare':
            a.add_argument('--project',type=Path)
            a.add_argument('--output',type=Path,required=True)
            a.add_argument('--families',nargs='+',choices=('transport','mosaic','relay','dial'))
            a.add_argument('--levels',nargs='+',type=int,choices=(1,2,3))
            a.add_argument('--cases',nargs='+',help='Explicit published task IDs')
            a.add_argument('--views',nargs='+',choices=('front','side'),default=['front','side'])
            a.add_argument('--duration-s',type=float,help='Optional short preview cap; omit for the full edited timeline')
            a.add_argument('--width',type=int,default=1920);a.add_argument('--height',type=int,default=1080)
            a.add_argument('--samples',type=int,default=64)
            a.add_argument('--mode',choices=('desks','promo'),default='desks')
            a.add_argument('--device',choices=('METAL','OPTIX','CUDA','CPU'))
    run=sub.add_parser('run');run.add_argument('--plan',type=Path,required=True)
    run.add_argument('--index',type=int,required=True);run.add_argument('--blender');run.add_argument('--scratch',type=Path)
    status=sub.add_parser('status');status.add_argument('--plan',type=Path,required=True)
    submit=sub.add_parser('submit');submit.add_argument('--plan',type=Path,required=True)
    submit.add_argument('--partition',required=True);submit.add_argument('--parallel',type=int,default=1)
    submit.add_argument('--cpus',type=int,default=20);submit.add_argument('--memory',default='64G')
    submit.add_argument('--time',dest='wall_time',default='24:00:00');submit.add_argument('--blender')
    submit.add_argument('--dry-run',action='store_true')
    args=vars(p.parse_args());command=args.pop('command')
    if command=='export':result=bundle.export(**args)
    elif command=='pack':result=bundle.pack(args['data_root'],args['output'])
    elif command=='setup':result=bundle.setup(args.pop('config'),args.pop('data_root'),**args)
    elif command=='verify':result=bundle.verify(args['data_root'])
    elif command=='doctor':result=server.doctor(**args)
    elif command=='import-motion':result=server.import_motion(**args)
    elif command=='project':
        from robofrontier.factory.editorial import create
        result=create(**args)
    elif command=='edit-video':
        from robofrontier.factory.editorial import render
        result=render(args['project'],args['input'],args['output'])
    elif command=='prepare':result=server.prepare(**args)
    elif command=='run':result=server.run_job(args.pop('plan'),**args)
    elif command=='status':result=server.status(args['plan'])
    elif command=='submit':result=server.submit(args.pop('plan'),**args)
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
