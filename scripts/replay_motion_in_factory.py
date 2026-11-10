"""Replay immutable source states and optional scene-independent cuts in a factory.

No commands, IK, contacts or physics are executed. Relative hardware layout and
geometry stay identical; materials/background and a rigid world placement may vary.
"""
import argparse,json
from pathlib import Path
import numpy as np
from robofrontier.media.motion_recording import MotionReader
from robofrontier.media.motion_timeline import sample_timeline,resolve_timeline
from robofrontier.media.replay_edit import ReplayEdit
from robofrontier.physics.workstation import Workstation
from robofrontier.factory.workstations import FactoryPlayback
from robofrontier.factory.playback import current_scene
from robofrontier.runtime.setup import write_json


def video_sample(stamp,deadline,rate=30):
    if stamp+1e-9<deadline:return False,deadline
    while deadline<=stamp+1e-9:deadline+=1/rate
    return True,deadline


def replay(recording,factory,output,render=False,timeline=None,speed=20.,fps=30.,table_opening_scale=.5,translation_m=None,yaw_rad=None,max_frames=None,keep_idle=False,edit_timeline=None):
    if render:raise ValueError('Factory video now uses Cycles: run python -m robofrontier.factory.commands video')
    reader=MotionReader(recording);source=Workstation(reader.path/'source');output=Path(output)
    if timeline is not None and edit_timeline is not None:raise ValueError("Choose one edit reference")
    timeline=None if keep_idle else resolve_timeline(recording,timeline or edit_timeline)
    edit=ReplayEdit(timeline,reader)if timeline else None
    if edit is not None and edit.exact:speed,fps=edit.speed,edit.fps
    selected=edit.select(speed,fps)if edit else sample_timeline(np.ones(reader.meta['frames'],bool),reader.meta['sample_hz'],speed,fps)
    if not render and edit is None and max_frames is None:selected=np.arange(reader.meta['frames'])
    if max_frames is not None:
        if max_frames<1:raise ValueError('max_frames must be positive')
        # Distributed verification/preview samples, not a truncated success video.
        selected=selected[np.unique(np.linspace(0,len(selected)-1,min(max_frames,len(selected))).astype(int))]
    play=FactoryPlayback(factory)
    presentation=play.configure_workstation(reader.meta['case_id'],source,table_opening_scale,translation_m,yaw_rad)
    output.mkdir(parents=True,exist_ok=False)
    frames=0;maximum_error=0.;image_times=[];indices=[]
    case=reader.meta['case_id'];names=play.manifest['workstation_names'][case]['geom_names'];initial=reader.meta['initial_rgba'];source.model.geom_rgba[:]=initial
    ids={g['id']:g['source_index']for g in source.manifest['geometries']};play.appearance(case,{name:initial[index]for name,index in ids.items()})
    events=iter(reader.events());event=next(events,None)
    for index,stamp,qpos in reader.selected_frames(selected):
        if edit is not None and abs(stamp-edit.times[index])>1e-9:raise ValueError('Timeline timestamp differs from recorded state')
        while event is not None and event['sim_time_s']<=stamp+1e-9:
            if event['event']=='rgba':
                play.appearance(case,event['geoms'])
                for name,value in event['geoms'].items():source.model.geom_rgba[ids[name]]=value
            event=next(events,None)
        expected=play.apply(case,source,qpos,stamp);frames+=1
        for name,target in names.items():maximum_error=max(maximum_error,float(np.linalg.norm(play.data.geom_xpos[play.model.geom(target).id]-expected['geometries'][name]['position_m'])))
        image_times.append(stamp);indices.append(index)
        if frames%300==0:print('factory states',frames,flush=True)
    check=None
    report=dict(scope='Recorded-state FK + rigid factory placement; no physics, commands, IK or resimulation',case_id=case,states_checked=frames,maximum_geometry_position_error_m=maximum_error,passed=maximum_error<1e-6,record_status=reader.meta['status'],video_decode=check,video_source_timestamps_s=image_times,replayed_source_timestamps_s=image_times,video_source_indices=indices,timeline=str(Path(timeline).resolve())if edit else None,timeline_arrays_sha256=edit.meta['arrays_sha256']if edit else None,speedup=speed,fps=fps,presentation=presentation,distributed_preview=max_frames is not None)
    write_json(output/'report.json',report)
    if not report['passed']:raise RuntimeError('Recorded-state replay verification failed')
    print(json.dumps({k:v for k,v in report.items()if k not in ['video_source_timestamps_s','video_source_indices']}),flush=True);return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('recording',type=Path);p.add_argument('--factory',type=Path,default=current_scene());p.add_argument('--output',type=Path,required=True);p.add_argument('--render',action='store_true');p.add_argument('--timeline','--edit-timeline',type=Path);p.add_argument('--keep-idle',action='store_true');p.add_argument('--speed',type=float,default=20);p.add_argument('--fps',type=float,default=30);p.add_argument('--table-opening-scale',type=float,default=.5);p.add_argument('--translation-m',type=float,nargs=3);p.add_argument('--yaw-rad',type=float);p.add_argument('--max-frames',type=int);a=p.parse_args();replay(a.recording,a.factory,a.output,a.render,a.timeline,a.speed,a.fps,a.table_opening_scale,a.translation_m,a.yaw_rad,a.max_frames,a.keep_idle)
