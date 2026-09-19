# Screen Recorder (Ubuntu X11)

在 Ubuntu 的 X11 桌面会话里,框选一块锁定画幅比(16:9 或 3:2)的区域,录制其画面与系统声音,输出 1080p MP4(H.264 + AAC),画面不含鼠标光标。个人自用,追求稳定、够用、低打扰。

## 依赖
- Ubuntu,运行于 X11(Xorg)会话(不支持 Wayland)
- `ffmpeg`,需含 `libx264`、`aac` 编码器与 Pulse 输入(验证:`ffmpeg -encoders 2>/dev/null | grep -iE 'libx264|aac'`)
- PipeWire(经 `pipewire-pulse` 提供 Pulse 兼容层)或 PulseAudio,提供默认 monitor 源
- Python 3.10+

系统依赖(Ubuntu):
```bash
sudo apt install ffmpeg python3-venv
# 音频走 PipeWire 时(22.04+ 默认),确认兼容层已装:
sudo apt install pipewire-pulse
```

## 安装
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 运行
```bash
.venv/bin/python -m app.main
```

## 使用
1. 选择画幅比(16:9 / 3:2)。
2. 点 **Select Region**,拖拽框选一个锁定该比例的矩形(Esc / 右键取消)。
3. 点 **Record** 开始;若检测不到系统音源,会询问是否继续无声录制。
4. 点 **Stop** 结束,文件保存到 `~/Videos/screen_YYYYmmdd-HHMMSS.mp4`,窗口显示路径。

## 边界(Scope)
- 只录系统声音,不录麦克风。
- 不含鼠标光标(`-draw_mouse 0`;屏幕上光标仍可见)。
- 无暂停/续录;一次「开始 → 停止」产出一个文件。
- 单主显示器;不做多屏/跨屏。
- 仅 X11;Wayland 不受支持。

## 测试
```bash
.venv/bin/python -m pytest                      # 单元 + 逻辑测试(无需真实显示)
RUN_E2E=1 .venv/bin/python -m pytest tests/test_e2e_smoke.py   # 真机捕获冒烟(需 X + ffmpeg + 音频)
```
