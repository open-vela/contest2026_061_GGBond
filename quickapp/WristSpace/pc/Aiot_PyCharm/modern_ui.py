import json
import queue
import time
from tkinter import (
    BOTH, END, LEFT, RIGHT, TOP, X, Y,
    BooleanVar, Button, Canvas, Checkbutton, Entry, Frame, Label, LabelFrame,
    Listbox, Scrollbar, StringVar, Text, Tk, Toplevel,
)
from tkinter import ttk


BG = "#0b1018"
PANEL = "#121a27"
PANEL_2 = "#182232"
TEXT = "#eef3fb"
MUTED = "#97a6bd"
TEAL = "#2b8f82"
BLUE = "#2864d7"
GREEN = "#2d8765"
RED = "#c84b62"
PURPLE = "#7251b5"
ORANGE = "#b87824"


class ModernBridgeApp:
    def __init__(self, center, start_server):
        self.center = center
        self.server = start_server()
        self.demo_jobs = []
        self.inventory_signature = ""

        self.root = Tk()
        self.root.title("腕控空间 AIoT 上位机")
        # Keep the initial window inside the usable desktop area so the log
        # footer and the panel scrollbars are visible on smaller displays.
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        window_w = min(1560, max(1240, screen_w - 80))
        window_h = min(940, max(720, screen_h - 110))
        self.root.geometry("{}x{}".format(window_w, window_h))
        self.root.minsize(1240, 720)
        self.root.resizable(True, True)
        self.root.configure(bg=BG)

        self.target_text = StringVar(value="当前候选：客厅灯")
        self.command_text = StringVar(value="等待发送")
        self.new_device_name = StringVar(value="手机")
        self.new_device_type = StringVar(value="phone")
        self.new_device_zone = StringVar(value="随身")
        self.device_name = StringVar(value="")
        self.device_type = StringVar(value="switch")
        self.device_zone = StringVar(value="AIoT新增")
        self.quick_device = StringVar(value="手机 / phone / 随身")
        self.action_name = StringVar(value="")
        self.action_command = StringVar(value="custom_action")
        self.action_summary = StringVar(value="")
        self.binding_summary = StringVar(value="指令绑定：等待同步")
        self.text_input = StringVar(value="打开客厅灯")
        self.training_action = StringVar(value="")
        self.training_reference = StringVar(value="请选择当前设备动作")
        self.manual_sample = StringVar(value="")
        self.inference_sample = StringVar(value="")
        self.training_status = StringVar(value="模型：等待动作")
        self.workflow_status = StringVar(value="流程：等待配置")
        self.current_payload = StringVar(value="尚未发送数据")
        self.safety_summary = StringVar(value="安全门控：开启 / 阈值 80%")
        self.mode_summary = StringVar(value="模式：演示")
        self.ai_model_summary = StringVar(value="模型 0/0 · 待配置")
        self.ai_result_summary = StringVar(value="Top 候选：等待识别")
        self.ai_gate_summary = StringVar(value="门控 80% · 候选间隔 4%")
        self.ai_protocol_summary = StringVar(value="输入协议：EMG4 + IMU9 · 50Hz/32帧")

        self._configure_tree_style()
        self._build_header()
        self._build_body()
        self._build_log_area()
        self.refresh_inventory_views(force=True)
        self.refresh_training_fields(force_reference=True)
        self.root.after(180, self.poll_updates)

    def _configure_tree_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "History.Treeview",
            background="#0d1420",
            fieldbackground="#0d1420",
            foreground=TEXT,
            rowheight=25,
            borderwidth=0,
        )
        style.configure(
            "History.Treeview.Heading",
            background="#253247",
            foreground=TEXT,
            relief="flat",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map("History.Treeview", background=[("selected", "#285a75")])

    def _build_header(self):
        header = Frame(self.root, bg=BG, padx=18, pady=12)
        header.pack(side=TOP, fill=X)
        left = Frame(header, bg=BG)
        left.pack(side=LEFT, fill=X, expand=True)
        Label(
            left,
            text="腕控空间 · 多模态 AIoT 调试中心",
            bg=BG,
            fg=TEXT,
            font=("Microsoft YaHei UI", 17, "bold"),
            anchor="w",
        ).pack(side=TOP, fill=X)
        Label(
            left,
            text="PC人工采集肌电 + 九轴数据，训练个性化动作模型，并与 openvela 手表双向同步。",
            bg=BG,
            fg=MUTED,
            font=("Microsoft YaHei UI", 10),
            anchor="w",
        ).pack(side=TOP, fill=X, pady=(4, 0))
        right = Frame(header, bg=BG)
        right.pack(side=RIGHT)
        Label(right, textvariable=self.target_text, bg=BG, fg="#62dfcb",
              font=("Microsoft YaHei UI", 11, "bold")).pack(side=TOP, anchor="e")
        Label(right, textvariable=self.command_text, bg=BG, fg=MUTED,
               font=("Microsoft YaHei UI", 9)).pack(side=TOP, anchor="e", pady=(4, 0))
        Label(right, textvariable=self.safety_summary, bg=BG, fg="#f4c55f",
              font=("Microsoft YaHei UI", 9, "bold")).pack(side=TOP, anchor="e", pady=(4, 0))
        Label(right, textvariable=self.mode_summary, bg=BG, fg="#8fd8ff",
               font=("Microsoft YaHei UI", 9, "bold")).pack(side=TOP, anchor="e", pady=(4, 0))
        Label(right, textvariable=self.workflow_status, bg=BG, fg="#f4c55f",
              font=("Microsoft YaHei UI", 9, "bold")).pack(side=TOP, anchor="e", pady=(4, 0))

    def _build_body(self):
        body = Frame(self.root, bg=BG, padx=12, pady=0)
        body.pack(side=TOP, fill=BOTH, expand=True)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=9, uniform="column")
        body.grid_columnconfigure(1, weight=10, uniform="column")
        body.grid_columnconfigure(2, weight=13, uniform="column")

        control = LabelFrame(
            body, text=" 手势与联动控制 ", bg=PANEL, fg=TEXT,
            font=("Microsoft YaHei UI", 11, "bold"), padx=6, pady=6,
        )
        control.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        management = LabelFrame(
            body, text=" 设备与动作管理 ", bg=PANEL, fg=TEXT,
            font=("Microsoft YaHei UI", 11, "bold"), padx=6, pady=6,
        )
        management.grid(row=0, column=1, sticky="nsew", padx=6)
        training = LabelFrame(
            body, text=" AI 数据采集、训练与调试 ", bg=PANEL, fg=TEXT,
            font=("Microsoft YaHei UI", 11, "bold"), padx=6, pady=6,
        )
        training.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        control_content = self._scrollable_panel(control)
        management_content = self._scrollable_panel(management)
        training_content = self._scrollable_panel(training)
        self._build_control_panel(control_content)
        self._build_management_panel(management_content)
        self._build_training_panel(training_content)

    def _scrollable_panel(self, parent):
        canvas = Canvas(parent, bg=PANEL, highlightthickness=0, bd=0)
        scroll = Scrollbar(parent, orient="vertical", command=canvas.yview)
        content = Frame(canvas, bg=PANEL)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)

        def refresh_scrollregion(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_width(event):
            canvas.itemconfigure(window_id, width=event.width)

        def on_wheel(event):
            delta = -1 * int(event.delta / 120) if event.delta else 0
            canvas.yview_scroll(delta, "units")

        content.bind("<Configure>", refresh_scrollregion)
        canvas.bind("<Configure>", fit_width)
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", on_wheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
        return content

    def _button(self, parent, text, command, color, row=None, column=None, columnspan=1, width=13):
        button = Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg="#ffffff",
            activebackground=color,
            activeforeground="#ffffff",
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold"),
            width=width,
            height=2,
        )
        if row is None:
            button.pack(side=LEFT, padx=4, pady=4)
        else:
            button.grid(row=row, column=column, columnspan=columnspan, sticky="ew", padx=4, pady=4)
        return button

    def _build_control_panel(self, parent):
        Label(parent, text="基础手势", bg=PANEL, fg="#62dfcb",
              font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(fill=X)
        grid = Frame(parent, bg=PANEL)
        grid.pack(fill=X, pady=(4, 8))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        controls = [
            ("抬腕指向\n切换候选", "point_next", "抬腕指向", "#34445f"),
            ("顺时针\n连续调高", "rotate_cw", "顺时针", BLUE),
            ("逆时针\n连续调低", "rotate_ccw", "逆时针", BLUE),
            ("上摆\n开启设备", "swing_up", "上摆开启", GREEN),
            ("下摆\n关闭设备", "swing_down", "下摆关闭", PURPLE),
            ("回正过滤\n不执行动作", "neutral_return", "回正过滤", "#566176"),
            ("甩腕撤销\n撤销上一步", "flick_cancel", "甩腕撤销", RED),
            ("翻腕场景\n切换场景", "flip_scene", "翻腕场景", TEAL),
        ]
        for index, (text, command, label, color) in enumerate(controls):
            self._button(
                grid, text,
                lambda c=command, l=label: self.send_single_command(c, l),
                color, row=index // 2, column=index % 2, width=14,
            )

        Label(parent, text="高级流程", bg=PANEL, fg="#62dfcb",
              font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(fill=X, pady=(5, 0))
        loop_row = Frame(parent, bg=PANEL)
        loop_row.pack(fill=X, pady=(4, 2))
        loop_row.grid_columnconfigure(0, weight=1)
        self._button(
            loop_row, "AI闭环演示\n决策链可视化",
            self.start_closed_loop_demo,
            "#d3a238",
            row=0,
            column=0,
            width=18,
        )
        advanced = Frame(parent, bg=PANEL)
        advanced.pack(fill=X, pady=4)
        advanced.grid_columnconfigure(0, weight=1)
        advanced.grid_columnconfigure(1, weight=1)
        advanced_defs = [
            ("空间校准", "calibrate_space", "空间校准", TEAL, None),
            ("误触测试", "low_confidence_test", "误触测试", ORANGE, 52),
            ("数据流采样", "sensor_sample", "数据流采样", "#b29a35", None),
            ("个性匹配", "adaptive_match", "个性匹配", ORANGE, None),
            ("观影编排", "compose_movie", "观影编排", BLUE, None),
            ("离家编排", "compose_away", "离家编排", PURPLE, None),
        ]
        for index, (text, command, label, color, confidence) in enumerate(advanced_defs):
            self._button(
                advanced, text,
                lambda c=command, l=label, p=confidence: self.send_single_command(c, l, p),
                color, row=index // 2, column=index % 2, width=14,
            )

        utility = Frame(parent, bg=PANEL)
        utility.pack(fill=X, pady=(7, 2))
        utility.grid_columnconfigure(0, weight=1)
        utility.grid_columnconfigure(1, weight=1)
        self._button(utility, "同步初始状态", self.center.reset_state, GREEN, row=0, column=0)
        self._button(utility, "清空待发队列", self.center.clear_pending, "#3b4658", row=0, column=1)
        self._button(parent, "切换安全门控并同步", self.toggle_safety_guard, ORANGE, width=18)

        Label(parent, text="运行模式", bg=PANEL, fg="#62dfcb",
              font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(fill=X, pady=(8, 3))
        mode_grid = Frame(parent, bg=PANEL)
        mode_grid.pack(fill=X)
        for column in range(3):
            mode_grid.grid_columnconfigure(column, weight=1)
        self._button(mode_grid, "演示联调", lambda: self.send_mode("demo"), "#34445f", row=0, column=0, width=10)
        self._button(mode_grid, "采集训练", lambda: self.send_mode("training"), ORANGE, row=0, column=1, width=10)
        self._button(mode_grid, "模型识别", lambda: self.send_mode("inference"), BLUE, row=0, column=2, width=10)

        Label(parent, text="文本指令", bg=PANEL, fg="#62dfcb",
              font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(fill=X, pady=(10, 3))
        Entry(parent, textvariable=self.text_input, font=("Microsoft YaHei UI", 11),
              bg="#f6f8fb", fg="#111827", relief="flat").pack(fill=X, ipady=6)
        self._button(parent, "发送文本指令", self.send_text_command, "#3b4658", width=15)

    def _build_management_panel(self, parent):
        add_box = LabelFrame(
            parent, text=" 新增设备向导 ", bg=PANEL_2, fg="#62dfcb",
            font=("Microsoft YaHei UI", 10, "bold"), padx=8, pady=6,
        )
        add_box.pack(fill=X, pady=(0, 8))
        Label(
            add_box,
            text="这里是独立新增入口，不会被设备库选择覆盖。添加后会弹出动作配置，并同步到 AIoT。",
            bg=PANEL_2, fg=MUTED, font=("Microsoft YaHei UI", 9), anchor="w",
            wraplength=430,
        ).pack(fill=X, pady=(0, 4))
        guide_form = Frame(add_box, bg=PANEL_2)
        guide_form.pack(fill=X)
        self._labeled_entry(guide_form, "新增名称", self.new_device_name, 0, bg=PANEL_2)
        self._labeled_entry(guide_form, "新增类型", self.new_device_type, 1, bg=PANEL_2)
        self._labeled_entry(guide_form, "新增位置", self.new_device_zone, 2, bg=PANEL_2)
        quick_row = Frame(add_box, bg=PANEL_2)
        quick_row.pack(fill=X, pady=(3, 0))
        quick_row.grid_columnconfigure(0, weight=1)
        quick_row.grid_columnconfigure(1, weight=1)
        self._button(quick_row, "手机模板", lambda: self.use_device_template("手机", "phone", "随身"), "#3b4658", row=0, column=0)
        self._button(quick_row, "冰箱模板", lambda: self.use_device_template("冰箱", "fridge", "厨房"), "#3b4658", row=0, column=1)
        self._button(quick_row, "手动添加设备并配置动作", self.add_new_device_from_guide, GREEN, row=1, column=0, columnspan=2)

        Label(parent, text="设备库", bg=PANEL, fg="#62dfcb",
              font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(fill=X)
        device_list_frame = Frame(parent, bg=PANEL)
        device_list_frame.pack(fill=X, pady=(4, 6))
        self.device_list = Listbox(
            device_list_frame, height=5, bg="#0d1420", fg=TEXT,
            selectbackground="#285a75", selectforeground="#ffffff",
            relief="flat", font=("Microsoft YaHei UI", 10), exportselection=False,
        )
        device_scroll = Scrollbar(device_list_frame, orient="vertical", command=self.device_list.yview)
        self.device_list.configure(yscrollcommand=device_scroll.set)
        self.device_list.pack(side=LEFT, fill=X, expand=True)
        device_scroll.pack(side=RIGHT, fill=Y)
        self.device_list.bind("<<ListboxSelect>>", self.on_device_select)

        device_form = Frame(parent, bg=PANEL)
        device_form.pack(fill=X)
        self._labeled_entry(device_form, "当前名称", self.device_name, 0)
        self._labeled_entry(device_form, "当前类型", self.device_type, 1)
        self._labeled_entry(device_form, "当前位置", self.device_zone, 2)
        device_buttons = Frame(parent, bg=PANEL)
        device_buttons.pack(fill=X, pady=(3, 8))
        device_buttons.grid_columnconfigure(0, weight=1)
        device_buttons.grid_columnconfigure(1, weight=1)
        self._button(device_buttons, "更新当前设备", self.add_or_update_device, GREEN, row=0, column=0)
        self._button(device_buttons, "删除当前设备", self.delete_current_device, RED, row=0, column=1)
        self._button(device_buttons, "设为当前并同步", self.select_device_from_list, TEAL, row=1, column=0)
        self._button(device_buttons, "同步全部配置", self.center.sync_config, "#3b4658", row=1, column=1)

        Label(parent, text="当前设备动作", bg=PANEL, fg="#62dfcb",
              font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(fill=X, pady=(4, 0))
        self.action_list = Listbox(
            parent, height=5, bg="#0d1420", fg=TEXT,
            selectbackground="#285a75", selectforeground="#ffffff",
            relief="flat", font=("Microsoft YaHei UI", 10), exportselection=False,
        )
        self.action_list.pack(fill=X, pady=(4, 6))
        self.action_list.bind("<<ListboxSelect>>", self.on_action_select)

        action_form = Frame(parent, bg=PANEL)
        action_form.pack(fill=X)
        self._labeled_entry(action_form, "动作名称", self.action_name, 0)
        self._labeled_entry(action_form, "指令编码", self.action_command, 1)
        action_buttons = Frame(parent, bg=PANEL)
        action_buttons.pack(fill=X, pady=3)
        action_buttons.grid_columnconfigure(0, weight=1)
        action_buttons.grid_columnconfigure(1, weight=1)
        self._button(action_buttons, "添加 / 更新动作", self.add_or_update_action, TEAL, row=0, column=0)
        self._button(action_buttons, "删除选中动作", self.delete_action, RED, row=0, column=1)
        self._button(action_buttons, "执行选中动作", self.execute_action, BLUE, row=1, column=0)
        self._button(action_buttons, "一键默认映射", self.apply_default_command_bindings, ORANGE, row=1, column=1)
        Label(parent, textvariable=self.action_summary, bg=PANEL, fg=MUTED,
              justify=LEFT, anchor="w", wraplength=380,
              font=("Microsoft YaHei UI", 9)).pack(fill=X, pady=(5, 0))
        Label(parent, textvariable=self.binding_summary, bg="#101C2B", fg="#6FE4D1",
              justify=LEFT, anchor="w", wraplength=400, padx=8, pady=6,
              font=("Microsoft YaHei UI", 9, "bold")).pack(fill=X, pady=(5, 0))

    def _labeled_entry(self, parent, label, variable, row, bg=PANEL):
        parent.grid_columnconfigure(1, weight=1)
        Label(parent, text=label, bg=bg, fg=MUTED,
              font=("Microsoft YaHei UI", 9), anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 6), pady=3)
        Entry(parent, textvariable=variable, font=("Microsoft YaHei UI", 10),
              bg="#f6f8fb", fg="#111827", relief="flat").grid(row=row, column=1, sticky="ew", ipady=4, pady=3)

    def _build_training_panel(self, parent):
        action_row = Frame(parent, bg=PANEL)
        action_row.pack(fill=X)
        Label(action_row, text="训练动作", bg=PANEL, fg=MUTED,
              font=("Microsoft YaHei UI", 9)).pack(side=LEFT)
        Entry(action_row, textvariable=self.training_action, font=("Microsoft YaHei UI", 10),
              bg="#f6f8fb", fg="#111827", relief="flat").pack(side=LEFT, fill=X, expand=True, padx=6, ipady=4)
        self._button(action_row, "切换动作", self.select_current_training_action, "#3b4658", width=9)

        ai_box = LabelFrame(
            parent, text=" AI 能力展示 ", bg="#0d1420", fg="#62dfcb",
            font=("Microsoft YaHei UI", 10, "bold"), padx=8, pady=6,
        )
        ai_box.pack(fill=X, pady=(6, 7))
        ai_box.grid_columnconfigure(0, weight=1)
        ai_box.grid_columnconfigure(1, weight=1)
        self._ai_metric(ai_box, "模型状态", self.ai_model_summary, 0, 0, "#6FE4D1")
        self._ai_metric(ai_box, "识别结果", self.ai_result_summary, 0, 1, "#8fd8ff")
        self._ai_metric(ai_box, "安全门控", self.ai_gate_summary, 1, 0, "#f4c55f")
        self._ai_metric(ai_box, "数据入口", self.ai_protocol_summary, 1, 1, "#c8d5e8")

        Label(parent, textvariable=self.training_reference, bg=PANEL, fg="#f4c55f",
              justify=LEFT, anchor="w", wraplength=520,
              font=("Microsoft YaHei UI", 9)).pack(fill=X, pady=(5, 7))

        Label(parent, text="采集输入 · 最多记录 10 组", bg=PANEL, fg="#62dfcb",
              font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(fill=X)
        Entry(parent, textvariable=self.manual_sample, font=("Consolas", 10),
              bg="#f6f8fb", fg="#111827", relief="flat").pack(fill=X, ipady=6, pady=(4, 3))
        Label(
            parent,
            text="格式：e1,e2,e3,e4 | ax,ay,az | gx,gy,gz\n示例：0.580,0.420,0.200,0.160 | 0.800,9.300,2.100 | 0.150,-0.080,1.200",
            bg=PANEL, fg=MUTED, justify=LEFT, anchor="w",
            font=("Consolas", 9),
        ).pack(fill=X)

        train_buttons = Frame(parent, bg=PANEL)
        train_buttons.pack(fill=X, pady=5)
        for column in range(3):
            train_buttons.grid_columnconfigure(column, weight=1)
        self.capture_button = self._button(train_buttons, "记录本次数据", self.capture_training_sample, TEAL, row=0, column=0)
        self.train_button = self._button(train_buttons, "训练模型", self.train_current_model, GREEN, row=0, column=1)
        self.clear_button = self._button(train_buttons, "清空当前样本", self.clear_training_samples, RED, row=0, column=2)
        self._button(train_buttons, "同步AI模型", self.sync_ai_models, PURPLE, row=1, column=0)
        self._button(train_buttons, "准备采集流程", self.prepare_training, "#3b4658", row=1, column=1)
        self._button(train_buttons, "重置采集提示", lambda: self.refresh_training_fields(force_reference=True), "#3b4658", row=1, column=2)

        Label(parent, text="识别测试输入 · 训练完成后才可提交", bg=PANEL, fg="#62dfcb",
              font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(fill=X, pady=(7, 0))
        Entry(parent, textvariable=self.inference_sample, font=("Consolas", 10),
              bg="#f6f8fb", fg="#111827", relief="flat").pack(fill=X, ipady=6, pady=(4, 3))
        self.inference_button = self._button(parent, "输入一组数据并识别触发", self.simulate_ai_inference, BLUE, width=22)
        Label(parent,
              text="识别输入独立于采集输入：输入实际动作的一组 EMG + IMU 数据，AI 仅在模型已训练时执行。",
              bg=PANEL, fg=MUTED, justify=LEFT, anchor="w", wraplength=520,
              font=("Microsoft YaHei UI", 9)).pack(fill=X, pady=(0, 4))

        Label(parent, textvariable=self.training_status, bg=PANEL, fg=TEXT,
              justify=LEFT, anchor="w", wraplength=520,
              font=("Microsoft YaHei UI", 9, "bold")).pack(fill=X, pady=(2, 7))

        Label(parent, text="当前发送 / 接收数据", bg=PANEL, fg="#62dfcb",
              font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(fill=X)
        self.payload_text = Text(
            parent, height=4, bg="#0d1420", fg="#c8d5e8",
            insertbackground="#ffffff", relief="flat", font=("Consolas", 9), wrap="word",
        )
        self.payload_text.pack(fill=X, pady=(4, 7))

        Label(parent, text="当前动作最近 10 组采集历史", bg=PANEL, fg="#62dfcb",
              font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(fill=X)
        columns = ("index", "time", "emg", "accel", "gyro")
        self.history_tree = ttk.Treeview(
            parent, columns=columns, show="headings", height=6, style="History.Treeview",
        )
        headings = {
            "index": "#", "time": "时间", "emg": "肌电4通道",
            "accel": "加速度", "gyro": "陀螺仪",
        }
        widths = {"index": 34, "time": 66, "emg": 150, "accel": 110, "gyro": 110}
        for column in columns:
            self.history_tree.heading(column, text=headings[column])
            self.history_tree.column(column, width=widths[column], minwidth=30, anchor="center")
        self.history_tree.pack(fill=BOTH, expand=True, pady=(4, 0))

    def _ai_metric(self, parent, title, variable, row, column, color):
        frame = Frame(parent, bg="#0d1420")
        frame.grid(row=row, column=column, sticky="ew", padx=5, pady=4)
        Label(frame, text=title, bg="#0d1420", fg=MUTED,
              font=("Microsoft YaHei UI", 8), anchor="w").pack(fill=X)
        Label(frame, textvariable=variable, bg="#0d1420", fg=color,
              font=("Microsoft YaHei UI", 9, "bold"), anchor="w",
              wraplength=230, justify=LEFT).pack(fill=X, pady=(2, 0))

    def _build_log_area(self):
        frame = LabelFrame(
            self.root, text=" 双端通信日志 ", bg=PANEL, fg=TEXT,
            font=("Microsoft YaHei UI", 10, "bold"), padx=8, pady=6,
        )
        frame.pack(side=TOP, fill=X, padx=12, pady=(4, 8))
        self.log_text = Text(
            frame, height=4, bg="#080c12", fg="#d7deeb",
            insertbackground="#ffffff", relief="flat", font=("Consolas", 9),
        )
        scroll = Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)

    def send_single_command(self, command, title, confidence=None):
        self.cancel_demo_jobs()
        if command == "point_next":
            self.queue_next_device(title)
            return
        if command == "sensor_sample":
            self.center.enqueue("sensor_sample", "数据流采样",
                                accel={"x": 2.4, "y": 7.6, "z": 5.8}, confidence=84)
        elif command == "compose_movie":
            self.center.enqueue("compose_scene", "观影编排", confidence=95,
                                extra={"sceneKey": "movie", "sceneLabel": "观影"})
        elif command == "compose_away":
            self.center.enqueue("compose_scene", "离家编排", confidence=95,
                                extra={"sceneKey": "away", "sceneLabel": "离家"})
        else:
            self.center.enqueue(command, title, confidence=confidence)
        self.refresh_header()

    def start_closed_loop_demo(self):
        self.cancel_demo_jobs()
        result = self.center.start_closed_loop_demo()
        self.refresh_header()
        if result.get("ignored"):
            self.command_text.set("AI闭环演示已在运行")
        else:
            self.command_text.set("AI闭环演示已启动 · 8步")

    def toggle_safety_guard(self):
        enabled = bool(self.center.settings.get("safetyGuardEnabled", True))
        self.center.settings["safetyGuardEnabled"] = not enabled
        self.center.settings["safetyThreshold"] = int(self.center.settings.get("safetyThreshold", 80) or 80)
        state = "开启" if self.center.settings["safetyGuardEnabled"] else "暂停"
        self.center.save_config()
        self.center.sync_config("安全门控：" + state)
        self.center.log("安全门控已{}，阈值 {}%".format(state, self.center.settings["safetyThreshold"]))
        self.refresh_header()

    def send_mode(self, mode):
        self.center.set_operation_mode(mode)
        self.refresh_header()

    def queue_next_device(self, label="抬腕指向"):
        with self.center.lock:
            if not self.center.devices:
                return
            self.center.device_index = (self.center.device_index + 1) % len(self.center.devices)
            target = dict(self.center.current_device())
        self.center.enqueue(
            "point_next",
            label,
            extra={
                "targetDeviceId": target.get("id"),
                "targetDeviceName": target.get("name"),
                "selectionVersion": int(time.time() * 1000),
            },
        )
        self.refresh_inventory_views(force=True)
        self.refresh_header()

    def select_device_from_list(self):
        selection = self.device_list.curselection()
        if selection:
            self.center.device_index = selection[0]
        target = self.center.current_device()
        self.center.enqueue(
            "point_next",
            "PC选择设备：" + target.get("name", ""),
            extra={
                "targetDeviceId": target.get("id"),
                "targetDeviceName": target.get("name"),
                "selectionVersion": int(time.time() * 1000),
            },
        )
        self.refresh_inventory_views(force=True)

    def on_device_select(self, _event=None):
        selection = self.device_list.curselection()
        if not selection or selection[0] >= len(self.center.devices):
            return
        device = self.center.devices[selection[0]]
        self.device_name.set(device.get("name", ""))
        self.device_type.set(device.get("type", "switch"))
        self.device_zone.set(device.get("zone", "AIoT新增"))

    def on_action_select(self, _event=None):
        actions = self.center.current_device_actions()
        selection = self.action_list.curselection()
        if not selection or selection[0] >= len(actions):
            return
        action = actions[selection[0]]
        self.action_name.set(action.get("name", ""))
        self.action_command.set(action.get("command", "custom_action"))
        self.center.training_action_id = action.get("id", "")
        self.training_action.set(action.get("name", ""))
        self.refresh_training_fields(force_reference=True)

    def add_or_update_device(self):
        device = self.center.add_device(
            self.device_name.get(), self.device_type.get(), self.device_zone.get(),
        )
        if device:
            self.refresh_inventory_views(force=True)
            self.open_device_action_dialog(device)

    def add_new_device_from_guide(self):
        device = self.center.add_device(
            self.new_device_name.get(), self.new_device_type.get(), self.new_device_zone.get(),
        )
        if device:
            self.device_name.set(device.get("name", ""))
            self.device_type.set(device.get("type", "switch"))
            self.device_zone.set(device.get("zone", "AIoT新增"))
            self.refresh_inventory_views(force=True)
            self.open_device_action_dialog(device)

    def use_device_template(self, name, device_type, zone):
        self.new_device_name.set(name)
        self.new_device_type.set(device_type)
        self.new_device_zone.set(zone)

    def delete_current_device(self):
        selection = self.device_list.curselection()
        if selection and selection[0] < len(self.center.devices):
            self.center.device_index = selection[0]
        removed = self.center.delete_device(self.center.current_device().get("id"))
        if removed:
            self.refresh_inventory_views(force=True)

    def command_binding_summary_text(self):
        defaults = [
            ("开", "power_on"),
            ("关", "power_off"),
            ("高", "value_up"),
            ("低", "value_down"),
        ]
        actions = self.center.current_device_actions()
        parts = []
        used = {}
        bound_count = 0
        for label, command_action in defaults:
            bound = None
            for action in actions:
                if action.get("commandAction") == command_action:
                    bound = action
                    break
            if bound:
                trigger = bound.get("triggerName") or bound.get("triggerCommand") or bound.get("command") or "已绑定"
                trigger_key = bound.get("triggerCommand") or bound.get("command") or trigger
                used[trigger_key] = used.get(trigger_key, 0) + 1
                parts.append("{}→{}".format(label, trigger))
                bound_count += 1
            else:
                parts.append("{}→未绑定".format(label))
        conflict = any(count > 1 for count in used.values())
        status = "存在冲突，请调整" if conflict else ("可直接联动" if bound_count == len(defaults) else "待补齐")
        return "指令绑定：{}\n完整度：{}/{}，{}".format(" / ".join(parts), bound_count, len(defaults), status)

    def apply_default_command_bindings(self):
        device = self.center.current_device()
        if not device:
            return
        defaults = [
            ("开启", "power_on", "上摆", "swing_up"),
            ("关闭", "power_off", "下摆", "swing_down"),
            ("调高", "value_up", "顺时针", "rotate_cw"),
            ("调低", "value_down", "逆时针", "rotate_ccw"),
        ]
        actions = []
        for title, command_action, trigger_name, trigger_command in defaults:
            actions.append({
                "id": "{}_{}".format(device.get("id"), command_action),
                "name": "{}{}指令".format(device.get("name", ""), title),
                "command": trigger_command,
                "commandAction": command_action,
                "triggerName": trigger_name,
                "triggerCommand": trigger_command,
                "isCustomTrigger": False,
                "description": "PC 一键默认指令映射",
                "deviceId": device.get("id"),
                "targetDeviceId": device.get("id"),
                "deviceName": device.get("name", ""),
            })
        self.center.merge_actions(actions)
        self.center.training_action_id = actions[0].get("id", "")
        self.center.log("一键默认映射: {}".format(device.get("name", "")))
        self.center.sync_config("一键默认映射：" + device.get("name", ""))
        self.refresh_inventory_views(force=True)
        self.refresh_training_fields(force_reference=True)

    def add_or_update_action(self):
        action = self.center.add_action(
            self.action_name.get(), self.action_command.get(),
            "PC上位机设备专属动作",
        )
        if action:
            self.center.training_action_id = action.get("id", "")
            self.refresh_inventory_views(force=True)
            self.refresh_training_fields(force_reference=True)

    def delete_action(self):
        removed = self.center.delete_action(self.action_name.get())
        if removed:
            self.refresh_inventory_views(force=True)
            self.refresh_training_fields(force_reference=True)

    def execute_action(self):
        device = self.center.current_device()
        action = {
            "name": self.action_name.get() or "自定义动作",
            "command": self.action_command.get() or "custom_action",
            "description": "PC上位机动作",
            "deviceId": device.get("id"),
            "targetDeviceId": device.get("id"),
            "deviceName": device.get("name"),
        }
        self.center.enqueue(
            "custom_action", action["name"],
            extra={
                "targetDeviceId": device.get("id"),
                "targetDeviceName": device.get("name"),
                "actionDef": action,
            },
        )

    def send_text_command(self):
        self.center.parse_text_command(self.text_input.get(), "PC文本")
        self.refresh_inventory_views(force=True)

    def open_device_action_dialog(self, device):
        dialog = Toplevel(self.root)
        dialog.title("配置设备动作 - " + device.get("name", ""))
        dialog.geometry("560x420")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        Label(
            dialog, text="为「{}」选择默认动作".format(device.get("name", "")),
            bg=BG, fg=TEXT, font=("Microsoft YaHei UI", 15, "bold"),
            anchor="w", padx=20, pady=14,
        ).pack(fill=X)
        Label(
            dialog,
            text="保存后会立即同步到手表端。后续可继续在设备与动作管理区修改。",
            bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 10),
            anchor="w", padx=20,
        ).pack(fill=X)
        option_area = Frame(dialog, bg=BG, padx=20, pady=12)
        option_area.pack(fill=X)
        adjustable = device.get("type") in ("light", "ac", "speaker", "fridge", "fan", "tv")
        option_defs = [
            ("开启设备", device.get("name", "") + "开启", "swing_up", True),
            ("关闭设备", device.get("name", "") + "关闭", "swing_down", True),
            ("连续调高", device.get("name", "") + "调高", "rotate_cw", adjustable),
            ("连续调低", device.get("name", "") + "调低", "rotate_ccw", adjustable),
        ]
        options = []
        for label, action_name, command, checked in option_defs:
            variable = BooleanVar(value=checked)
            Checkbutton(
                option_area, text="{}  ->  {}".format(label, command), variable=variable,
                bg=BG, fg=TEXT, activebackground=BG, activeforeground=TEXT,
                selectcolor=PANEL_2, font=("Microsoft YaHei UI", 11), anchor="w",
            ).pack(fill=X, pady=4)
            options.append((variable, action_name, command))

        custom = Frame(dialog, bg=BG, padx=20, pady=6)
        custom.pack(fill=X)
        custom_name = StringVar(value="")
        custom_command = StringVar(value="custom_action")
        Label(custom, text="自定义", bg=BG, fg=MUTED).pack(side=LEFT, padx=(0, 6))
        Entry(custom, textvariable=custom_name, width=18).pack(side=LEFT, padx=4)
        Entry(custom, textvariable=custom_command, width=18).pack(side=LEFT, padx=4)

        def save_actions():
            for variable, action_name, command in options:
                if variable.get():
                    self.center.add_action(
                        action_name, command, "设备创建向导添加",
                        device.get("id"), device.get("name"), sync=False,
                    )
            if custom_name.get().strip():
                self.center.add_action(
                    custom_name.get().strip(),
                    custom_command.get().strip() or "custom_action",
                    "设备创建向导自定义",
                    device.get("id"), device.get("name"), sync=False,
                )
            self.center.sync_config("设备动作已更新：" + device.get("name", ""))
            self.refresh_inventory_views(force=True)
            self.refresh_training_fields(force_reference=True)
            dialog.destroy()

        buttons = Frame(dialog, bg=BG, padx=20, pady=14)
        buttons.pack(fill=X)
        self._button(buttons, "保存并同步", save_actions, GREEN, width=12)
        self._button(buttons, "稍后配置", dialog.destroy, "#3b4658", width=10)

    @staticmethod
    def format_manual_values(values):
        emg = values.get("emg", [0, 0, 0, 0])
        accel = values.get("accel", {})
        gyro = values.get("gyro", {})
        return "{:.3f},{:.3f},{:.3f},{:.3f} | {:.3f},{:.3f},{:.3f} | {:.3f},{:.3f},{:.3f}".format(
            emg[0], emg[1], emg[2], emg[3],
            accel.get("x", 0), accel.get("y", 0), accel.get("z", 9.8),
            gyro.get("x", 0), gyro.get("y", 0), gyro.get("z", 0),
        )

    @staticmethod
    def parse_manual_values(text):
        normalized = (text or "").replace("，", ",").replace("；", "|").replace(";", "|")
        groups = [part.strip() for part in normalized.split("|")]
        if len(groups) != 3:
            raise ValueError("请输入三组数据：4路肌电 | 3轴加速度 | 3轴陀螺仪")
        emg = [float(value.strip()) for value in groups[0].split(",") if value.strip()]
        accel = [float(value.strip()) for value in groups[1].split(",") if value.strip()]
        gyro = [float(value.strip()) for value in groups[2].split(",") if value.strip()]
        if len(emg) != 4 or len(accel) != 3 or len(gyro) != 3:
            raise ValueError("数据数量错误，应为 4 | 3 | 3 个数值")
        return {
            "emg": emg,
            "accel": {"x": accel[0], "y": accel[1], "z": accel[2]},
            "gyro": {"x": gyro[0], "y": gyro[1], "z": gyro[2]},
        }

    def resolve_training_action(self):
        action = self.center.resolve_training_action(self.training_action.get().strip())
        if action:
            self.training_action.set(action.get("name", action.get("id", "")))
        return action

    def select_current_training_action(self):
        actions = self.center.current_device_actions()
        if not actions:
            self.center.log("当前设备没有动作，请先添加动作")
            return
        current_id = self.center.training_action_id
        index = 0
        for item_index, action in enumerate(actions):
            if action.get("id") == current_id:
                index = (item_index + 1) % len(actions)
                break
        self.center.training_action_id = actions[index].get("id", "")
        self.training_action.set(actions[index].get("name", ""))
        self.refresh_training_fields(force_reference=True)

    def prepare_training(self):
        action = self.resolve_training_action()
        if action:
            self.center.prepare_training_session(action.get("id"))

    def capture_training_sample(self):
        action = self.resolve_training_action()
        if not action:
            return
        model = self.center.model_summary(action.get("id")) or {}
        minimum = int(model.get("minSamples", 10) or 10)
        count = int(model.get("sampleCount", 0) or 0)
        if count >= minimum:
            self.center.log("采集已完成 {}/{}：按钮已锁定，不能继续写入".format(count, minimum))
            self.refresh_training_fields()
            return
        try:
            values = self.parse_manual_values(self.manual_sample.get())
            window = self.center.model_manager.manual_window(action, values, "pc_manual")
        except ValueError as error:
            self.center.log("数据录入失败：{}".format(error))
            return
        self.center.capture_training_sample(action.get("id"), window, "pc_manual")
        self.refresh_training_fields(force_reference=True)

    def train_current_model(self):
        action = self.resolve_training_action()
        if action:
            self.center.train_action_model(action.get("id"))
        self.refresh_training_fields()

    def simulate_ai_inference(self):
        action = self.resolve_training_action()
        if not action:
            return
        model = self.center.model_summary(action.get("id")) or {}
        if model.get("status") != "trained":
            self.center.log("识别不可用：请先完成 10 组采集并点击“训练模型”")
            self.refresh_training_fields()
            return
        try:
            values = self.parse_manual_values(self.inference_sample.get())
            window = self.center.model_manager.manual_window(action, values, "pc_manual_realtime")
        except ValueError as error:
            self.center.log("实时数据错误：{}".format(error))
            return
        self.center.infer_action(action.get("id"), window, "pc_manual_realtime")
        self.refresh_training_fields()

    def clear_training_samples(self):
        action = self.resolve_training_action()
        if action:
            self.center.clear_training_samples(action.get("id"))
        self.refresh_training_fields(force_reference=True)

    def sync_ai_models(self):
        self.center.sync_models()
        self.refresh_training_fields()

    def refresh_header(self):
        device = self.center.current_device()
        self.target_text.set("当前候选：{} · {}".format(
            device.get("name", ""), device.get("zone", "未分区"),
        ))
        queued = self.center.last_queued or {}
        self.command_text.set("最近发送：{} · seq {}".format(
            queued.get("label", "等待发送"), queued.get("seq", "-"),
        ))
        enabled = bool(self.center.settings.get("safetyGuardEnabled", True))
        threshold = int(self.center.settings.get("safetyThreshold", 80) or 80)
        self.safety_summary.set(
            "安全门控：{} / 阈值 {}%".format("开启" if enabled else "暂停", threshold)
        )
        labels = {"demo": "演示联调", "training": "采集训练", "inference": "模型识别"}
        self.mode_summary.set("模式：" + labels.get(self.center.settings.get("operationMode", "demo"), "演示联调"))

    def refresh_inventory_views(self, force=False):
        signature = json.dumps(
            {
                "devices": self.center.devices,
                "actions": self.center.actions,
                "index": self.center.device_index,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if not force and signature == self.inventory_signature:
            return
        self.inventory_signature = signature
        self.device_list.delete(0, END)
        for index, device in enumerate(self.center.devices):
            marker = "●" if index == self.center.device_index else " "
            self.device_list.insert(
                END,
                "{} {}  |  {}  |  {}".format(
                    marker, device.get("name", ""),
                    device.get("type", "switch"), device.get("zone", "未分区"),
                ),
            )
        if self.center.devices:
            self.device_list.selection_set(self.center.device_index)
            self.device_list.see(self.center.device_index)
            device = self.center.current_device()
            self.device_name.set(device.get("name", ""))
            self.device_type.set(device.get("type", "switch"))
            self.device_zone.set(device.get("zone", "AIoT新增"))

        actions = self.center.current_device_actions()
        self.action_list.delete(0, END)
        for action in actions:
            if action.get("commandAction"):
                command_text = "{} <- {}".format(
                    action.get("commandAction", ""),
                    action.get("triggerName") or action.get("triggerCommand") or action.get("command", ""),
                )
            else:
                command_text = action.get("command", "")
            self.action_list.insert(
                END, "{}  ->  {}".format(action.get("name", ""), command_text),
            )
        if actions:
            selected_index = 0
            for index, action in enumerate(actions):
                if action.get("id") == self.center.training_action_id:
                    selected_index = index
                    break
            self.action_list.selection_set(selected_index)
            action = actions[selected_index]
            self.action_name.set(action.get("name", ""))
            self.action_command.set(action.get("command", "custom_action"))
            self.training_action.set(action.get("name", ""))
        else:
            self.action_name.set("")
            self.action_command.set("custom_action")
            self.training_action.set("")
        self.action_summary.set(self.center.current_action_summary())
        self.binding_summary.set(self.command_binding_summary_text())
        self.refresh_header()

    def refresh_training_fields(self, force_reference=False):
        action = self.center.resolve_training_action(self.training_action.get().strip())
        if not action:
            self.workflow_status.set("流程：等待配置动作")
            self.training_status.set(
                "当前设备：{} | 暂无可训练动作，请先添加动作".format(
                    self.center.current_device().get("name", ""),
                )
            )
            self.training_reference.set("添加动作后，按提示录入 10 组数据。")
            total = len(self.center.recognition_models())
            trained = sum(1 for item in self.center.recognition_models() if item.get("status") == "trained")
            self.ai_model_summary.set("已训练 {}/{} · 待配置动作".format(trained, total))
            self.ai_result_summary.set("Top 候选：等待识别")
            self.ai_gate_summary.set("门控 {}% · 候选间隔 4%".format(
                int(self.center.settings.get("safetyThreshold", 80) or 80)
            ))
            self.ai_protocol_summary.set("输入协议：EMG4 + IMU9 · 50Hz/32帧")
            for button_name in ("capture_button", "train_button", "clear_button", "inference_button"):
                button = getattr(self, button_name, None)
                if button:
                    button.configure(state="disabled")
            self.refresh_history(None)
            return
        self.training_action.set(action.get("name", ""))
        model = self.center.model_summary(action.get("id")) or {}
        count = model.get("sampleCount", 0)
        minimum = model.get("minSamples", 10)
        status_map = {
            "untrained": "未训练", "collecting": "采集中",
            "ready": "可训练", "trained": "已训练",
        }
        status = status_map.get(model.get("status", "untrained"), model.get("status", "未训练"))
        workflow = self.center.workflow_state(action.get("id"))
        self.workflow_status.set("流程：{} · {}/{}".format(
            workflow.get("label", "等待配置"),
            workflow.get("sampleCount", count),
            workflow.get("minSamples", minimum),
        ))
        self.training_status.set(
            "设备：{} | 动作：{} | 样本：{}/{} | 模型：{} | 质量：{}% | 阈值：{}%".format(
                action.get("deviceName", ""), action.get("name", ""),
                count, minimum, status, model.get("quality", 0), model.get("threshold", 80),
            )
        )
        self.refresh_ai_showcase(action, model, status, count, minimum)
        if model.get("status") == "trained":
            self.training_reference.set("模型已训练。请在下方“识别测试输入”填写一组实时数据，再点击识别触发。")
            if force_reference or not self.inference_sample.get().strip():
                reference = self.center.model_manager.reference_values(action, 0)
                self.inference_sample.set(self.format_manual_values(reference))
        elif count >= minimum:
            self.training_reference.set("10 组数据已采集完成，采集入口已锁定，请点击“训练模型”。")
        else:
            reference = self.center.model_manager.reference_values(action, count)
            self.training_reference.set(
                "第 {}/{} 组：完整做一次“{}”，在参考值附近输入并保留少量自然波动。".format(
                    count + 1, minimum, action.get("name", ""),
                )
            )
            if force_reference or not self.manual_sample.get().strip():
                self.manual_sample.set(self.format_manual_values(reference))

        capture_enabled = count < minimum
        train_enabled = count >= minimum and model.get("status") != "trained"
        infer_enabled = model.get("status") == "trained"
        if hasattr(self, "capture_button"):
            self.capture_button.configure(state="normal" if capture_enabled else "disabled")
        if hasattr(self, "train_button"):
            self.train_button.configure(state="normal" if train_enabled else "disabled")
        if hasattr(self, "clear_button"):
            self.clear_button.configure(state="normal" if count > 0 else "disabled")
        if hasattr(self, "inference_button"):
            self.inference_button.configure(state="normal" if infer_enabled else "disabled")
        self.refresh_history(action.get("id"))

    def refresh_ai_showcase(self, action, model, status, count, minimum):
        models = self.center.recognition_models()
        trained = sum(1 for item in models if item.get("status") == "trained")
        quality = int(model.get("quality", 0) or 0)
        threshold = int(model.get("threshold", self.center.settings.get("safetyThreshold", 80)) or 80)
        self.ai_model_summary.set("已训练 {}/{} · 当前{} · 质量{}%".format(
            trained, len(models), status, quality,
        ))
        self.ai_gate_summary.set("门控 {}% · 候选间隔 4% · {}/{}".format(
            threshold, count, minimum,
        ))
        self.ai_protocol_summary.set("输入协议：EMG4 + IMU9 · 50Hz/32帧")

        queued = self.center.last_queued or {}
        predictions = queued.get("predictions") or []
        inference = queued.get("inference") or {}
        if not predictions and isinstance(inference, dict):
            predictions = inference.get("ranking", [])
        if predictions:
            best = predictions[0]
            accepted = "通过" if inference.get("accepted") else "待判定"
            self.ai_result_summary.set("Top：{} {}% · {}".format(
                best.get("actionName") or best.get("name") or action.get("name", "动作"),
                best.get("confidence", 0),
                accepted,
            ))
        elif model.get("status") == "trained":
            self.ai_result_summary.set("Top 候选：模型就绪，等待实时数据")
        else:
            self.ai_result_summary.set("Top 候选：等待训练完成")

    def refresh_history(self, action_id):
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        if not action_id:
            return
        history = self.center.sample_history(action_id, 10)
        for index, sample in enumerate(history, 1):
            manual = sample.get("manualValues") or {}
            emg = manual.get("emg") or []
            accel = manual.get("accel") or {}
            gyro = manual.get("gyro") or {}
            captured = sample.get("capturedAt", 0) / 1000
            time_text = time.strftime("%H:%M:%S", time.localtime(captured)) if captured else "-"
            if emg:
                emg_text = ",".join("{:.2f}".format(value) for value in emg)
                accel_text = "{:.2f},{:.2f},{:.2f}".format(
                    accel.get("x", 0), accel.get("y", 0), accel.get("z", 0),
                )
                gyro_text = "{:.2f},{:.2f},{:.2f}".format(
                    gyro.get("x", 0), gyro.get("y", 0), gyro.get("z", 0),
                )
            else:
                features = sample.get("features", [])
                emg_text = "历史特征"
                accel_text = ",".join(str(value) for value in features[:3])
                gyro_text = ",".join(str(value) for value in features[3:6])
            self.history_tree.insert(
                "", END, values=(index, time_text, emg_text, accel_text, gyro_text),
            )

    def refresh_payload_view(self):
        payload = {
            "manualInput": self.manual_sample.get(),
            "inferenceInput": self.inference_sample.get(),
            "lastQueued": self.center.last_queued,
            "lastDelivered": self.center.last_delivered,
            "lastWatchInput": self.center.last_watch_input,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        self.payload_text.delete("1.0", END)
        self.payload_text.insert(END, text)

    def poll_updates(self):
        while True:
            try:
                line = self.center.ui_events.get_nowait()
                self.log_text.insert(END, line + "\n")
                self.log_text.see(END)
            except queue.Empty:
                break
        self.refresh_inventory_views()
        self.refresh_training_fields()
        self.refresh_payload_view()
        self.refresh_header()
        self.root.after(250, self.poll_updates)

    def cancel_demo_jobs(self):
        while self.demo_jobs:
            job = self.demo_jobs.pop()
            try:
                self.root.after_cancel(job)
            except Exception:
                pass

    def run(self):
        self.root.mainloop()
