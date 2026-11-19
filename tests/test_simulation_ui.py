from pathlib import Path
import os
import sys
import time
import traceback

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clothing_design
from clothing_design import ops


def main():
    assert not bpy.app.background
    clothing_design.register()
    window = bpy.context.window_manager.windows[0]
    stage = "draft"
    heartbeat_frames = set()
    started = 0.0

    def tick():
        nonlocal stage, started
        try:
            area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
            region = next(r for r in area.regions if r.type == 'WINDOW')
            with bpy.context.temp_override(window=window, area=area, region=region):
                if stage == "draft":
                    assert bpy.ops.cd.import_character(figure="MAN") == {'FINISHED'}
                    assert bpy.ops.cd.add_garment(preset="TSHIRT") == {'FINISHED'}
                    stage = "launch"
                elif stage == "launch":
                    scene = bpy.context.scene
                    scene.cd.stitch_frames = 10
                    scene.cd.settle_frames = 8
                    started = time.monotonic()
                    assert bpy.ops.cd.drape('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
                    assert not bpy.ops.cd.settle.poll()
                    stage = "drape"
                elif stage == "drape":
                    result = ops.simulation_status()
                    if result["state"] == "running":
                        if "frame" in result:
                            heartbeat_frames.add(result["frame"])
                    else:
                        assert result["state"] == "finished" and result["frame"] == 19, result
                        assert len(heartbeat_frames) >= 4, heartbeat_frames
                        elapsed = time.monotonic() - started
                        print(f"Drape completed in {elapsed:.1f}s with UI callbacks on "
                              f"{len(heartbeat_frames)} simulation frames", flush=True)
                        assert bpy.ops.cd.relax('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
                        stage = "relax"
                elif stage == "relax":
                    result = ops.simulation_status()
                    assert result["state"] == "running", result
                    if result.get("stage_frame", 0) >= 3:
                        window.event_simulate(type='ESC', value='PRESS',
                                              x=region.x + 10, y=region.y + 10)
                        stage = "cancel"
                elif stage == "cancel":
                    result = ops.simulation_status()
                    if result["state"] != "running":
                        assert result["state"] == "cancelled" and result["frame"] < 169, result
                        assert bpy.ops.cd.settle('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
                        stage = "settle"
                elif stage == "settle":
                    result = ops.simulation_status()
                    if result["state"] != "running":
                        assert result["state"] == "finished", result
                        print("Escape cancelled Relax and the next Settle completed", flush=True)
                        bpy.ops.wm.quit_blender()
                        return None
        except Exception:
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(1)
        return 0.04

    bpy.app.timers.register(tick, first_interval=0.5)


if __name__ == "__main__":
    main()
