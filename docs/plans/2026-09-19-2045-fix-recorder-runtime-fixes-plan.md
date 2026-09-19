---
title: "录屏工具运行期修复 - Plan"
type: fix
date: 2026-09-19
topic: recorder-runtime-fixes
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# 录屏工具运行期修复 - Plan

## Goal Capsule

- **Objective:** 用户在 Ubuntu X11 上运行录屏工具时，能清楚地看到已选中的录制区域、在录制中看到已录时长、并能自行指定视频保存目录，从而无需猜测即可完成一次完整的录制。
- **Means:** 三处聚焦改动 —— 选区覆盖层增加「框选后常驻显示 + 显式确认」、主窗口增加录制计时器、增加保存目录选择器（KTD1/KTD2/KTD3）。
- **Authority:** jianfeng（个人自用，产品决策权威）。
- **Stop conditions:** 三个问题各自的验收示例（AE1–AE3）通过；既有 39 单测 + 2 真实捕获 e2e 全部保持通过；无回归。
- **Execution profile:** 在功能分支上按 U1→U2→U3→U4 增量提交，每个单元可独立成 commit；先易后难、尽早跑回归。
- **Owner:** ce-work 执行，jianfeng 验收。

## Product Contract

### Summary
针对运行 `app.main` 后发现的三个运行期问题，做三处聚焦修复：(1) 框选区域后选框常驻可见并需显式确认，让用户清楚选中了什么；(2) 录制时显示已录时长；(3) 允许用户选择保存目录（默认仍为 ~/Videos）。不改变既有捕获管线（x11grab + pulse monitor + libx264/AAC）、画幅锁定逻辑，或「单次开始→停止产出一个文件、无暂停」的行为。

### Problem Frame
上一版（见 Sources 的 origin 计划）已能框选并录出 1080p MP4，但三处 UX 缺口使实际使用「黑盒」：选定区域后选框立即消失、无法确认范围；录制时无时长反馈；保存位置写死在 ~/Videos 不可改。这是个人自用工具的可用性缺口，非功能损坏。

### Key Decisions
- **框选后需显式确认再开始录制**（KTD1 落地）：释放鼠标后覆盖层不立即关闭，常驻显示选框 + 尺寸，用户点一下/回车确认后才真正锁定区域并允许按 Record。Governs R1, AE1。
  - 备选（Deferred to Follow-Up）：非交互常驻边框（点击穿透）——少一次点击，但需额外窗口与生命周期管理。
- **录制计时显示「已录时长」（从开始到当前的 MM:SS），而非起始墙钟时间**（KTD2）：更符合「录了多久」的心智。Governs R2, AE2。
- **保存路径选择粒度为「目录」，而非「完整文件名」**（KTD3）：文件名带时间戳由程序生成，用户只需选目录；默认 ~/Videos，未选则沿用默认。Governs R3, AE3。

### Requirements
- R1. 框选完成后，选框及其尺寸在确认前持续可见；用户可显式确认（点击/回车）以锁定该区域，也可重新拖选或 Esc 取消。
- R2. 录制进行中，界面显示已录时长，且随时间递增（至少秒级精度）。
- R3. 用户可在录制前指定保存目录；未指定时保存目录为 ~/Videos；所选目录用于每次录制的输出路径。

### Key Flows
- F1. 选定区域（修复后）
  - Trigger: 用户点 "Select Region"。
  - Steps: 覆盖层覆盖全屏 → 拖拽框出锁定画幅的矩形（实时显示尺寸）→ 释放鼠标，选框常驻 + 尺寸可见 → 用户点击选区/按 Enter 确认（或重新拖选、Esc 取消）→ 确认后主窗口 Record 可用。
  - Covers R1.
- F2. 录制（修复后）
  - Steps: 点 Record → 进入录制，界面显示递增的已录时长（MM:SS）→ 点 Stop → 停止并在所选目录产出 MP4、提示路径。
  - Covers R2.
- F3. 指定保存目录（修复后）
  - Trigger: 用户点 "Choose…"（或等效控件）→ 目录选择对话框 → 选择目录 → 后续录制写入该目录；未选则为 ~/Videos。
  - Covers R3.

### Acceptance Examples
- AE1. **Given** 16:9 画幅，**When** 拖拽框选后释放鼠标，**Then** 选框与尺寸持续可见（不立即消失），需点击/回车才确认；Esc 或重新拖选可改变结果。Covers R1.
- AE2. **Given** 正在录制，**When** 观察界面 5 秒以上，**Then** 显示的已录时长从约 00:00 递增到约 00:05（秒级精度）。Covers R2.
- AE3. **Given** 用户把保存目录改为 <某目录>，**When** 完成一次录制，**Then** MP4 落在 <某目录>；**Given** 未改目录，**When** 完成录制，**Then** MP4 落在 ~/Videos。Covers R3.

### Scope Boundaries
**Deferred to Follow-Up Work:**
- 保存目录跨启动持久化（记忆上次选择，写入 ~/.config）。
- 多显示器 / 跨屏选区。
- 暂停 / 继续 / 分段录制。
- 非交互常驻边框方案（若确认显式确认体验不合意再切换）。

**Outside this product's identity:**
- 录制后编辑（裁剪/字幕）、麦克风/多音源混音、全局快捷键、其它发行版打包。

### Success Criteria
- 从启动到「看到选框→确认→看到计时→停止→在所选目录得到 MP4」全程无猜测、无黑盒步骤。
- 既有 39 个单测 + 2 个真实捕获 e2e 保持通过（无回归）。

### Sources / Research
- 既有实现与计划：`docs/plans/2026-07-11-2253-feat-linux-screen-recorder-plan.md`（U1–U5 已实现并验证）。
- 相关代码：`app/overlay.py`（选区/覆盖层）、`app/mainwindow.py`（主窗口/状态）、`app/controller.py`（状态机 / from_defaults）、`app/encoder.py`（make_output_path / build_args）。

---

## Planning Contract

### Key Technical Decisions
- KTD1. **选区：两阶段确认（覆盖层常驻）。** 覆盖层在释放鼠标后不 close，进入「provisional」态继续绘制选框 + 尺寸 + 提示；`SelectionModel` 增状态机（IDLE → DRAGGING → PROVISIONAL），用「点击（位移 < 阈值）且已有 provisional → 确认」与「真实拖拽 → 新 provisional」区分；Enter/Space 亦可确认；Esc/右键取消。纯逻辑留在 `SelectionModel`（可无显示单测）。Governs R1, AE1.
- KTD2. **计时：主窗口 QTimer（1 Hz）驱动独立 QLabel，显示「已录时长」。** 进入 RECORDING 记录起点（`QElapsedTimer`），每 tick 计算 elapsed 并格式化为 MM:SS（≥1h 则 HH:MM:SS）；离开 RECORDING 停止并复位。`format_duration(seconds)` 抽为纯函数以便单测。Governs R2, AE2.
- KTD3. **保存目录：QFileDialog 目录选择器 + controller 持有 `save_dir`。** `make_path` 契约增加可选 `base_dir` 参数（`make_output_path` 已支持）；`RecordingController` 增 `set_save_dir(dir)` 与 `_save_dir`，`_begin` 用 `self._make_path(base_dir=self._save_dir)`；默认 None → ~/Videos。跨启动持久化不在本期。Governs R3, AE3.

### Assumptions
- 运行于 Ubuntu X11 会话、有可用 ffmpeg（libx264/aac/pulse）与 PipeWire/pulse 默认 monitor 源（与 origin 一致）。
- 现有 39 单测（offscreen）+ 2 真实捕获 e2e（RUN_E2E=1）是可用的回归基线。
- 选区「确认」采用覆盖层内点击/回车（非穿透边框），符合 KTD1 备选取舍。

### Sequencing
U1（计时）与 U2（保存目录）相互独立、均仅触及 mainwindow/controller 局部；U3（选区两阶段）是最大改动、仅触及 overlay + test_overlay；U4 集成 + 文档收尾。建议顺序：U1 → U2 → U3 → U4。U4 依赖 U1/U2/U3。

---

## Implementation Units

### U1. 录制计时器（R2 / AE2）
- **Goal:** 录制时显示递增的已录时长（MM:SS）。
- **Requirements:** R2, AE2.
- **Dependencies:** 无。
- **Files:** `app/formatting.py`（新增，纯函数）、`app/mainwindow.py`、`tests/test_formatting.py`（新增）。
- **Approach:**
  1. `formatting.py` 提供 `format_duration(seconds: float) -> str`：`<3600` → `MM:SS`（两位零填充）；`>=3600` → `HH:MM:SS`。
  2. `MainWindow` 新增 `self._time_label = QLabel("")`（初始空）加入布局（Stop 按钮之后、stretch 之前）；新增 `QTimer`（interval 1000 ms）。
  3. `_on_state_changed`：进入 RECORDING → 启动 `QElapsedTimer`、启动 timer；否则 → 停 timer、清空/复位 label。
  4. timer tick → `label.setText(format_duration(elapsed_ms/1000))`。
- **Patterns to follow:** 现有 `_on_state_changed` 的按钮启停写法；QLabel 布局既有习惯。
- **Test scenarios:**
  - `format_duration(0)` → `"00:00"`；`format_duration(5)` → `"00:05"`；`format_duration(65)` → `"01:05"`；`format_duration(3599.9)` → `"59:59"`；`format_duration(3600)` → `"01:00:00"`；`format_duration(3661)` → `"01:01:01"`。
  - （offscreen）构造 MainWindow，驱动 controller 进入 RECORDING，断言 time_label 非空且随 tick 递增；离开 RECORDING 后清空。
- **Verification:** 单测 `test_formatting.py` 全绿；offscreen 下主窗口能构造；真实会话点 Record 后 label 显示递增 MM:SS，Stop 后复位。

### U2. 保存目录选择器（R3 / AE3）
- **Goal:** 用户可指定保存目录；默认 ~/Videos。
- **Requirements:** R3, AE3.
- **Dependencies:** 无。
- **Files:** `app/controller.py`、`app/encoder.py`、`app/mainwindow.py`、`tests/test_controller.py`、`tests/test_encoder_args.py`。
- **Approach:**
  1. `encoder.make_output_path` 已接受 `base_dir`，保持不变（已含同秒冲突后缀逻辑）。
  2. `RecordingController`：新增 `self._save_dir = None` 与 `set_save_dir(dir)`（存 Path 或 None）；`_begin` 内改为 `self._out_path = self._make_path(base_dir=self._save_dir)`。`__init__` 的 `make_path` 契约约定为可接受 `base_dir=None` 关键字（默认 `make_output_path` 天然满足）。
  3. `MainWindow`：在状态区新增 "Save to: <当前目录> [Choose…]" 控件；Choose 触发 `QFileDialog.getExistingDirectory`（初始目录为当前或 ~/Videos），非空则 `controller.set_save_dir(path)` 并更新 label；默认 label 显示 `~/Videos`。
  4. 测试中注入的 `make_path` lambda 更新为可接受 `base_dir=None`。
- **Patterns to follow:** 既有注入式依赖（make_recorder / audio_available / make_path）。
- **Test scenarios:**
  - `make_output_path(base_dir=<tmp>)` 落在 <tmp>；`base_dir=None` 走默认目录（用 monkeypatch 指向临时 home，避免污染真实 ~/Videos）。
  - controller `set_save_dir(<dir>)` 后 `_begin` 生成的 out_path 在 <dir> 下（用 FakeRecorder 捕获 out_path）。
  - `set_save_dir(None)` → 回退默认目录。
  - 同秒冲突后缀行为保持（已有测试，勿回归）。
- **Verification:** 单测全绿；真实会话选目录后录制，MP4 落入所选目录；不选则落 ~/Videos。

### U3. 选区两阶段确认（R1 / AE1）
- **Goal:** 框选后选框常驻可见，需显式确认，消除「选完不知道选了哪」。
- **Requirements:** R1, AE1.
- **Dependencies:** 无。
- **Files:** `app/overlay.py`、`tests/test_overlay.py`。
- **Approach:**
  1. `SelectionModel` 增成员：`_press`、`_provisional`、常量 `CONFIRM_CLICK_THRESHOLD = 4`。状态推导：有 anchor → DRAGGING；无 anchor 且有 `_provisional` → PROVISIONAL；否则 IDLE。
  2. `press(x,y)`：记 `_press=(x,y)`、`_anchor=(x,y)`、`_region=None`。
  3. `move(x,y)`：有 anchor 时 `_region = snap_to_ratio(...)`（逻辑不变）。
  4. `release(x,y) -> tuple[Optional[Region], bool]`（返回 `(region, is_confirm)`）：
     - 位移 = `hypot(x-_press.x, y-_press.y)`。
     - 位移 ≥ 阈值：`_provisional = _region`，清 anchor/region，返回 (`_provisional`, False) —— 新 provisional，覆盖层保持。
     - 位移 < 阈值且 `_provisional is not None`：返回 (`_provisional`, True) —— 确认。
     - 位移 < 阈值且无 provisional：返回 (None, False) —— 空操作。
  5. `confirm() -> Optional[Region]`：返回 `_provisional`（供 Enter/Space）。
  6. `cancel()`：清 `_anchor/_region/_provisional`。
  7. `region` 属性：`return self._region or self._provisional`（绘制优先 live，其次 provisional）。
  8. `RegionOverlay`：`mouseReleaseEvent` 改为 `region, confirm = self._model.release(p.x(), p.y())`；`confirm and region` → `emit(region_selected); close()`；否则仅 `update()`（覆盖层常驻）。`keyPressEvent` 增 Enter/Space → `region = self._model.confirm()`，有则 `emit; close()`。`paintEvent` 在 PROVISIONAL（非 dragging）时仍绘制选框 + 尺寸，并追加提示 "Click / Enter to confirm · drag to re-select · Esc to cancel"。
  9. 控制器/主窗口接口不变（`selection_finished(region)` 仍在确认时触发）；`begin_selection`、`selection_cancelled` 语义不变。
- **Patterns to follow:** 既有 `SelectionModel` 纯状态机 + `RegionOverlay` 薄壳分层；`snap_to_ratio` 不动。
- **Test scenarios（纯 SelectionModel，无显示）:**
  - 覆盖 AE1：press → move(大位移) → release → 返回 (region, False)，`model.region` 非空（provisional 常驻）；再 press → (同点小位移)release → 返回 (同 region, True) 确认。
  - release 后 `model.region` 仍非空（常驻可见，不立即清空）。
  - 重新拖选：provisional 存在时 press → move(另一大位移) → release → `_provisional` 被新区域替换。
  - `cancel()` 后 `_provisional is None`。
  - Enter 确认：`confirm()` 返回当前 `_provisional`。
  - 空操作：IDLE 时小位移 press/release → 返回 (None, False)。
  - 极小拖拽仍被 `snap_to_ratio` 抬到 MIN_SHORT_SIDE（保持既有最小尺寸行为）。
  - `snap_to_ratio` 既有用例保持（勿回归）。
- **Verification:** `test_overlay.py` 全绿；真实会话拖选 → 选框常驻 + 尺寸 → 点击/Enter 确认 → Record 可用；Esc 取消、重新拖选均符合预期。

### U4. 集成 + 回归 + 文档（收尾）
- **Goal:** 串联三修复，确认无回归，更新使用说明。
- **Requirements:** Success Criteria。
- **Dependencies:** U1, U2, U3.
- **Files:** `README.md`（运行/使用说明）、（如需）`tests/` 集成点。
- **Approach:**
  1. 全量跑 `QT_QPA_PLATFORM=offscreen pytest tests/ -q`（预期原 39 + 新增单测全绿，2 e2e 跳过）。
  2. 真实会话 `RUN_E2E=1 QT_QPA_PLATFORM=offscreen DISPLAY=:1 pytest tests/test_e2e_smoke.py -v`（AE2/AE3/F2 不回归）。
  3. 手动冒烟：启动 → 选区(常驻 + 确认) → 改目录 → 录制(看计时) → 停止 → 到所选目录得 1080p MP4、无光标。
  4. `README.md` 增补：确认交互、计时显示、目录选择说明。
- **Test scenarios:** 以既有 e2e + 手动冒烟为准；新增行为已由 U1–U3 单测覆盖。
- **Verification:** 上述命令全绿；手动冒烟三修复均可见且生效。
