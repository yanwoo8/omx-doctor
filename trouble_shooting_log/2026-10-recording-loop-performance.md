# Where the recording loop time went

October 2026. LeRobot recording on a GPU-less VM, two cameras, 30 fps target.

## Visualization cost more than everything else

The recording loop was running slower than the target and episodes were coming
out with inconsistent timing. The first suspicion was camera decoding.

Profiling the loop showed the live visualization telemetry (`--display_data=true`)
accounted for 57.6 percent of the work per iteration. It was the largest single
item, on a host with no GPU to absorb it.

| | Loop time | Headroom at 30 fps (33.3 ms budget) |
| --- | --- | --- |
| `--display_data=true` | 13.9 ms | 19.4 ms |
| `--display_data=false` | 5.2 ms | 28.4 ms |

Turning it off was the whole fix. Worth checking before suspecting the model or
the cameras, because it is one flag and it is the default-on path.

## Camera settings that worked

Both cameras needed the pixel format spelled in uppercase. Lowercase `mjpg` was
not accepted:

```yaml
fourcc: MJPG
backend: V4L2
```

Dataset image keys as recorded: `observation.images.top` and
`observation.images.wrist`.

## Depth was not usable

An OAK-D Pro depth camera was considered for the top view. LeRobot's upstream
camera backends are OpenCVCamera, ZMQCamera, RealSenseCamera and Reachy2Camera.
There is no DepthAI or OAK backend, so the device could only be used as a plain
RGB camera through OpenCV, and the depth stream could not be recorded into a
dataset.

It would not have helped anyway. The policy being trained takes
`observation.state` of 6 values and three RGB images of 3 by 256 by 256, with no
depth input, so a recorded depth channel would have had nowhere to go.

Adding one would mean a camera plugin: a package named `lerobot_camera_*`
registering a config class with `@CameraConfig.register_subclass("name")`. Not
attempted.

## One master on the bus

RS-485 is half duplex and allows exactly one master. Running a diagnostic script
while LeRobot held the port corrupted traffic for both, and the symptom was
random communication failures rather than anything that pointed at the cause.

Everything had to be stopped before any direct motor access. This is the warning
at the top of the tool's help output.
