"""Render stored physical configurations, including the shared chunked format.

The directory is an Oracle trial (report.json, scene.xml, motion/) or a policy
run's private/outputs (evaluation.json, motion/ with its frozen source scene).
A policy run renders at its family's release speedup with stationary intervals
removed, unless --keep-idle or an explicit --speed/--timeline is given.

Only kinematics and appearance events are restored. No commands, IK, contact
solve or new physical integration are executed to manufacture a video.
New renders halve an existing rectangular central table opening by default;
use --table-opening-scale 1 for the original frozen tabletop presentation.
"""
import argparse,json,subprocess,time
from pathlib import Path
import mujoco,numpy as np
from PIL import Image,ImageDraw
from robofrontier.suite.evaluate import DIGITS
from robofrontier.cube_transport import _font
from robofrontier.run_setup import write_json
from robofrontier.motion_recording import MotionReader,digest
from robofrontier.replay_edit import ReplayEdit


def trial_report(directory):
    """An Oracle trial's report, or the same fields for a policy run's outputs."""
    if (directory/'report.json').exists():return json.loads((directory/'report.json').read_text()),directory/'scene.xml'
    stream=json.loads((directory/'motion/stream.json').read_text())
    evaluation=json.loads((directory/'evaluation.json').read_text())
    report=dict(case_id=stream['case_id'],scene_sha256=stream['source_scene_sha256'],passed=evaluation.get('task_success'),
        policy_run=True,matched_goals=evaluation.get('matched_goals'),total_goals=evaluation.get('total_goals'))
    # The run's saved scene.xml has portable asset paths; the frozen source is the exact scene.
    return report,directory/'motion/source/scene.xml'


def policy_speedup(directory):
    """The family speedup of the release frozen with a policy run."""
    task=json.loads((directory.parent/'inputs/task.json').read_text())
    release=json.loads((directory.parent/'inputs/family-release.json').read_text())
    return float(release['families'][task['family']]['speedup'])


def stationary_cut(recording,output):
    """Write the meaningful-motion cut of a recording (robofrontier.motion_cut)."""
    from robofrontier.motion_cut import meaningful_keep,write_cut
    times,keep,moving=meaningful_keep(recording)
    return write_cut(Path(output)/'stationary-cut.json',recording,times,keep,dict(moving_windows=int(moving.sum()),windows=len(moving)))


def render(directory,views=('global','global_rear'),speed=None,every=None,output=None,table_opening_scale=.5,timeline=None,fps=30.,keep_idle=False,encoder_threads=1,edit_timeline=None,width=None,height=None):
    if timeline is not None and edit_timeline is not None:raise ValueError("Choose one edit reference")
    timeline=timeline or edit_timeline
    if encoder_threads<1:raise ValueError("Positive encoder thread count required")
    directory=Path(directory).resolve();report,scene=trial_report(directory)
    target=Path(output) if output else directory/'video'
    if report.get('policy_run'):
        if speed is None:speed=policy_speedup(directory)
        if timeline is None and not keep_idle:timeline=stationary_cut(directory/'motion',target)
    if speed is None:speed=20.
    # Policy runs render quickly at 720p; Oracle trials keep their 1280 x 800 frame.
    width=width or 1280;height=height or (720 if report.get('policy_run') else 800)
    if digest(scene)!=report['scene_sha256']:raise ValueError('Trial scene checksum differs from physical report')
    model=mujoco.MjModel.from_xml_path(str(scene));data=mujoco.MjData(model)
    from robofrontier.suite.table_presentation import scale_rectangular_opening_for_render
    presentation=scale_rectangular_opening_for_render(model,table_opening_scale)
    # Display only, as in the Factory: a letter label under a robot base slides out.
    from robofrontier.factory.labels import robot_label_moves
    if mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_KEY,'initial')>=0:mujoco.mj_resetDataKeyframe(model,data,model.key('initial').id)
    family=json.loads((scene.parent/'task.json').read_text()).get('family') if (scene.parent/'task.json').is_file() else None
    mujoco.mj_kinematics(model,data);label_moves=robot_label_moves(model,data,avoid_objects=family!='mosaic')
    for name,move in label_moves.items():
        gid=model.geom(name).id;model.geom_pos[gid][:2]=move['to_xy'];model.geom_quat[gid]=move['quat_wxyz']
    shared=(directory/'motion/stream.json').exists();events=None;event=None
    if shared:
        reader=MotionReader(directory/'motion')
        if reader.meta['source_scene_sha256']!=report['scene_sha256']:raise ValueError('Motion source differs from physical report')
        if not reader.meta['frames']:raise ValueError('No recorded states')
        source_hz=float(reader.meta['sample_hz']);stream=((t,q,None) for t,q in reader.frames())
        model.geom_rgba[:]=reader.meta['initial_rgba'];events=iter(reader.events());event=next(events,None)
        registry=json.loads((reader.path/'source/workstation.json').read_text())
        geom_ids={g['id']:g['source_index'] for g in registry['geometries']}
    else:
        states=np.load(directory/'frame-states.npz')
        if len(states['time_s'])<2:raise ValueError('Insufficient legacy recorded states')
        source_hz=1/float(np.median(np.diff(states['time_s'])))
        stream=((float(t),q,int(d)) for t,q,d in zip(states['time_s'],states['qpos'],states['display']))
    edit=None;selection=None
    if shared and not keep_idle:
        from robofrontier.motion_timeline import resolve_timeline
        timeline=resolve_timeline(directory/'motion',timeline)
    if keep_idle:timeline=None
    if timeline is not None:
        if not shared:raise ValueError('Edited replay requires a shared motion recording')
        if every is not None:raise ValueError('Timeline sampling uses --fps, not --every')
        edit=ReplayEdit(timeline,reader)
        if edit.exact:speed,fps=edit.speed,edit.fps
        selection=set(edit.select(speed,fps).tolist())
    stream=((i,t,q,None)for i,t,q in reader.selected_frames(sorted(selection))) if edit else ((i,t,q,d)for i,(t,q,d)in enumerate(stream))
    every=max(1,round(speed*source_hz/fps)) if every is None else every
    if speed<=0 or every<1:raise ValueError('Positive playback speed and sampling stride required')
    if edit is None:fps=speed*source_hz/every
    target.mkdir(parents=True,exist_ok=True)
    processes={};started=time.monotonic();font=_font(22);rendered=0;source_frames=0;last=None;last_rendered=None
    for view in views:
        path=target/(view+'.mp4')
        if path.exists():raise FileExistsError(path)
        processes[view]=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-filter_threads','1','-filter_complex_threads','1','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r',str(fps),'-i','-','-an','-c:v','libx264','-threads',str(encoder_threads),'-crf','20','-preset','veryfast','-pix_fmt','yuv420p','-movflags','+frag_keyframe+empty_moov+default_base_moof',str(path)],stdin=subprocess.PIPE)
    commissioning=report.get('commissioning_only') or report.get('full_task_attempt') is False
    outcome=('MECHANICAL PASS' if report.get('passed') or report.get('local_passed') else 'MECHANICAL PARTIAL / FAILED') if commissioning else 'PASS' if report.get('passed') else 'UNIT PASS' if report.get('local_passed') else 'INTERRUPTED' if report.get('interrupted') else 'PARTIAL / FAILED'
    if report.get('engineering_assisted'):outcome+=' (engineering assisted)'
    if report.get('policy_run'):outcome=f"{report['matched_goals']}/{report['total_goals']} goals"
    producer='Policy' if report.get('policy_run') else 'Oracle'
    if presentation:outcome='SOURCE '+outcome
    try:
        with mujoco.Renderer(model,height=height,width=width) as renderer:
            def emit(stamp,q):
                data.qpos[:]=q;data.time=stamp
                mujoco.mj_kinematics(model,data);mujoco.mj_comPos(model,data);mujoco.mj_camlight(model,data)
                for view,process in processes.items():
                    renderer.update_scene(data,camera=view);image=Image.fromarray(renderer.render());draw=ImageDraw.Draw(image)
                    draw.rectangle((12,12,1000,73),fill=(245,242,235))
                    draw.text((23,18),f'{report["case_id"]} | {producer} {outcome} | recorded-state replay',font=font,fill=(23,32,43))
                    variant=f' | opening {table_opening_scale:g}x; render only' if presentation else ''
                    draw.text((23,43),f'{view} | sim {stamp:.1f} s | {speed:g}x | {source_hz:.1f} Hz source'+variant+(' | idle cut' if edit else ''),font=font,fill=(23,32,43))
                    process.stdin.write(image.tobytes())
                    if not rendered: image.save(target/(view+'-first.png'))
                    if shared and stamp==reader.meta['chunks'][-1]['end_sim_s']:image.save(target/(view+'-last.png'))
            for index,stamp,q,display in stream:
                while event is not None and event['sim_time_s']<=stamp+1e-9:
                    if event['event']=='rgba':
                        for name,value in event['geoms'].items():model.geom_rgba[geom_ids[name]]=value
                    event=next(events,None)
                if not shared and mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_GEOM,'score_0_0')>=0:
                    show=f'{display:02}' if display>=0 else '--'
                    for digit,char in enumerate(show):
                        for k,segment in enumerate('abcdefg'):
                            model.geom_rgba[model.geom(f'score_{digit}_{k}').id]=[.68,.13,.07,1 if segment in (DIGITS[int(char)] if char!='-' else 'g') else 0]
                source_frames+=1;last=(stamp,q)
                if edit is not None:
                    if index>=len(edit.times) or abs(stamp-edit.times[index])>1e-9:raise ValueError('Timeline timestamp differs from recorded state')
                    if index not in selection:continue
                elif index%every:continue
                emit(stamp,q);rendered+=1;last_rendered=stamp
                if rendered%300==0:print(f'{report["case_id"]} {views} rendered {rendered} frames',flush=True)
            if last is not None and last[0]!=last_rendered and edit is None:emit(*last);rendered+=1
            if edit is not None:
                if rendered!=len(selection):raise ValueError('Timeline/render frame count mismatch')
                source_frames=reader.meta['frames']
    finally:
        for process in processes.values():
            if process.stdin:process.stdin.close()
        codes=[process.wait() for process in processes.values()]
    if any(codes):raise RuntimeError('Video encoding failed '+str(codes))
    checks={}
    for view in views:
        path=target/(view+'.mp4');check=subprocess.run(['ffmpeg','-v','error','-threads','1','-filter_threads','1','-i',str(path),'-f','null','-'],capture_output=True,text=True)
        checks[view]=dict(path=str(path.resolve()),decode_passed=check.returncode==0,error=check.stderr or None)
    write_json(target/'manifest.json',dict(kind='Recorded-state FK rerender; no commands, IK, contacts or integration',source_trial=str(directory),source_scene_sha256=report['scene_sha256'],presentation_table=presentation,robot_labels_moved=sorted(label_moves),source_format='robofrontier.motion.v1' if shared else 'legacy_npz',recorded_source_hz=source_hz,speedup=speed,every=None if edit else every,fps=fps,source_frames=source_frames,rendered_states=rendered,wall_time_s=time.monotonic()-started,trial_passed=report.get('passed'),local_unit_passed=report.get('local_passed'),commissioning_only=report.get('commissioning_only',False),timeline=str(Path(timeline).resolve()) if edit else None,timeline_arrays_sha256=edit.meta['arrays_sha256'] if edit else None,views=checks))
    if not all(c['decode_passed'] for c in checks.values()):raise RuntimeError('A video could not be fully decoded')
    print(target,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('trial');p.add_argument('--speed',type=float,help='Default: 20, or a policy run family release speedup');p.add_argument('--fps',type=float,default=30);p.add_argument('--timeline','--edit-timeline',type=Path);p.add_argument('--keep-idle',action='store_true',help='Explicitly render the complete original clock');p.add_argument('--encoder-threads',type=int,default=1);p.add_argument('--every',type=int);p.add_argument('--output',type=Path);p.add_argument('--views',nargs='+',default=['global','global_rear']);p.add_argument('--table-opening-scale',type=float,default=.5,help='Offline presentation only; 1 preserves the original table');p.add_argument('--width',type=int);p.add_argument('--height',type=int);a=p.parse_args()
    render(a.trial,a.views,a.speed,a.every,a.output,a.table_opening_scale,a.timeline,a.fps,a.keep_idle,a.encoder_threads,width=a.width,height=a.height)
