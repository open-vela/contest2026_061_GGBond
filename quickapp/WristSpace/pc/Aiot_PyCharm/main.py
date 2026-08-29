import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from tkinter import (
    BOTH, BOTTOM, END, LEFT, RIGHT, TOP, X, Y,
    BooleanVar, Button, Checkbutton, Entry, Frame, Label, LabelFrame,
    Listbox, Scrollbar, StringVar, Text, Tk, Toplevel,
)
from tkinter import ttk

from multimodal_ai import MultimodalModelManager

HOST = "0.0.0.0"
PORT = 8787
ADB = r"C:\Users\Lenovo\.vela\sdk\tools\adb\win\adb.exe"
WATCH_PACKAGE = "com.application.watch.demo"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "aiot_config.json")
VENDOR_DIR = os.path.join(APP_DIR, "vendor")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

try:
    from Pinyin2Hanzi import DefaultDagParams, dag
except ImportError:
    DefaultDagParams = None
    dag = None


class AiotCommandCenter:
    def __init__(self):
        self.commands = queue.Queue()
        self.ui_events = queue.Queue()
        self.devices = [
            {"id": "light", "name": "客厅灯", "type": "light", "zone": "正前方"},
            {"id": "ac", "name": "空调", "type": "ac", "zone": "右前方"},
            {"id": "curtain", "name": "窗帘", "type": "curtain", "zone": "左前方"},
            {"id": "speaker", "name": "音箱", "type": "speaker", "zone": "右侧"},
        ]
        self.actions = [
            {"id": "movie_scene", "name": "观影场景", "command": "flip_scene", "description": "翻腕切换多设备场景"},
            {"id": "quick_freeze", "name": "冰箱速冻", "command": "fridge_quick_freeze", "description": "冰箱进入速冻模式"},
        ]
        # MULTIMODAL_AI_INTEGRATION_V1
        self.model_manager = MultimodalModelManager()
        self.training_action_id = ""
        self.last_manual_windows = {}
        self.demo_lock = threading.Lock()
        self.demo_running = False
        self.settings = {
            "safetyGuardEnabled": True,
            "safetyThreshold": 80,
            "operationMode": "demo",
        }
        # MANUAL_PC_CAPTURE_V2
        self.device_index = 0
        self.seq = 0
        self.config_version = 1
        self.lock = threading.Lock()
        self.last_poll_at = 0
        self.last_queued = None
        self.last_delivered = None
        self.last_watch_payload = None
        self.last_watch_input = None
        self.default_confidence = {
            "point_next": 88, "rotate_cw": 91, "rotate_ccw": 90,
            "swing_up": 87, "swing_down": 87, "neutral_return": 96,
            "flick_cancel": 90, "flip_scene": 92, "calibrate_space": 94,
            "low_confidence_test": 52, "sensor_sample": 84,
            "train_gesture": 94, "adaptive_match": 95, "compose_scene": 94,
            "sync_config": 96, "custom_action": 92,
            "training_sample": 90, "model_update": 96,
            "multimodal_inference": 94, "sync_models": 96,
            "training_session": 96, "inference_waiting": 96,
        }
        self.load_config()
        self.normalize_action_ownership()
        self.model_manager.sync_actions(self.actions)

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data.get("devices"), list) and data.get("devices"):
                self.devices = [dict(device) for device in data.get("devices") if isinstance(device, dict)]
            if isinstance(data.get("actions"), list):
                self.actions = [dict(action) for action in data.get("actions") if isinstance(action, dict)]
            self.device_index = int(data.get("deviceIndex") or 0)
            if self.device_index < 0 or self.device_index >= len(self.devices):
                self.device_index = 0
            self.config_version = max(self.config_version, int(data.get("configVersion") or 0))
            if isinstance(data.get("settings"), dict):
                self.settings.update(data.get("settings"))
            if data.get("operationMode"):
                self.settings["operationMode"] = data.get("operationMode")
            self.log("已加载本地配置: {} 台设备 / {} 个动作".format(len(self.devices), len(self.actions)))
        except Exception as error:
            self.log("本地配置加载失败: {}".format(error))

    def save_config(self):
        data = {
            "devices": self.devices,
            "actions": self.actions,
            "deviceIndex": self.device_index,
            "configVersion": self.config_version,
            "settings": self.settings,
            "savedAt": int(time.time() * 1000),
        }
        try:
            tmp_file = CONFIG_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            os.replace(tmp_file, CONFIG_FILE)
        except Exception as error:
            self.log("本地配置保存失败: {}".format(error))

    def normalize_action_ownership(self):
        """Repair legacy actions that predate device-scoped action binding."""
        changed = False
        for action in self.actions:
            device_id = action.get("deviceId") or action.get("targetDeviceId")
            if device_id:
                device = None
                for candidate in self.devices:
                    if candidate.get("id") == device_id:
                        device = candidate
                        break
                if device:
                    if not action.get("deviceId"):
                        action["deviceId"] = device.get("id")
                        changed = True
                    if not action.get("targetDeviceId"):
                        action["targetDeviceId"] = device.get("id")
                        changed = True
                    if not action.get("deviceName"):
                        action["deviceName"] = device.get("name", "")
                        changed = True
                continue

            text = "{} {}".format(action.get("name", ""), action.get("command", ""))
            inferred = None
            for device in self.devices:
                name = device.get("name", "")
                device_type = device.get("type", "")
                if name and name in text:
                    inferred = device
                    break
                if device_type and device_type in (action.get("command", "") or ""):
                    inferred = device
                    break
            if inferred is None and action.get("command") == "fridge_quick_freeze":
                for device in self.devices:
                    if device.get("id") == "fridge" or device.get("type") == "fridge":
                        inferred = device
                        break
            if inferred is None:
                continue
            action["deviceId"] = inferred.get("id")
            action["targetDeviceId"] = inferred.get("id")
            action["deviceName"] = inferred.get("name", "")
            changed = True

        if changed:
            self.config_version += 1
            self.save_config()
            self.log("已修复旧动作的设备归属并同步模型")

    def log(self, message):
        line = time.strftime("%H:%M:%S") + "  " + message
        print(line)
        self.ui_events.put(line)

    def current_device(self):
        if not self.devices:
            self.devices.append({"id": "light", "name": "客厅灯", "type": "light", "zone": "正前方"})
        if self.device_index < 0 or self.device_index >= len(self.devices):
            self.device_index = 0
        return self.devices[self.device_index]

    def make_id(self, name, prefix):
        known = {
            "冰箱": "fridge", "手机": "phone", "平板": "tablet", "电脑": "computer",
            "路由器": "router", "网关": "gateway", "电视": "tv", "风扇": "fan",
            "扫地机": "cleaner", "空气净化器": "purifier", "加湿器": "humidifier",
            "洗衣机": "washer",
        }
        if name in known:
            return known[name]
        base = "".join(ch.lower() for ch in name if ch.isascii() and ch.isalnum())
        return base or "{}{}".format(prefix, len(self.devices) + len(self.actions) + 1)

    def guess_device_type(self, name, fallback="switch"):
        pairs = [
            ("冰箱", "fridge"), ("手机", "phone"), ("平板", "tablet"),
            ("电脑", "computer"), ("路由器", "router"), ("网关", "gateway"),
            ("灯", "light"), ("空调", "ac"), ("窗帘", "curtain"),
            ("音箱", "speaker"), ("音响", "speaker"), ("电视", "tv"),
            ("风扇", "fan"), ("扫地", "cleaner"), ("净化器", "purifier"),
            ("洗衣机", "washer"),
        ]
        for word, device_type in pairs:
            if word in name:
                return device_type
        return fallback

    def find_device_index(self, name_or_id):
        key = (name_or_id or "").strip()
        if key in ("", "当前", "当前设备"):
            return self.device_index
        for index, device in enumerate(self.devices):
            name = device.get("name", "")
            if device.get("id") == key or name == key or (key and (key in name or name in key)):
                return index
        return -1

    def set_target_device(self, name_or_id):
        index = self.find_device_index(name_or_id)
        if index >= 0:
            self.device_index = index
            return self.current_device()
        return None

    def merge_devices(self, incoming, allow_delete=False):
        if not isinstance(incoming, list):
            return
        if allow_delete:
            self.devices = [dict(device) for device in incoming if isinstance(device, dict)]
            if not self.devices:
                self.devices.append({"id": "light", "name": "客厅灯", "type": "light", "zone": "正前方"})
            if self.device_index >= len(self.devices):
                self.device_index = len(self.devices) - 1
            return
        index_by_id = {device.get("id"): index for index, device in enumerate(self.devices)}
        index_by_name = {device.get("name"): index for index, device in enumerate(self.devices)}
        for raw in incoming:
            if not isinstance(raw, dict):
                continue
            device = dict(raw)
            device_id = device.get("id") or self.make_id(device.get("name", ""), "dev")
            device["id"] = device_id
            target_index = index_by_id.get(device_id)
            if target_index is None:
                target_index = index_by_name.get(device.get("name"))
            if target_index is None:
                self.devices.append(device)
                index_by_id[device_id] = len(self.devices) - 1
                index_by_name[device.get("name")] = len(self.devices) - 1
            else:
                self.devices[target_index].update(device)

    def merge_actions(self, incoming, allow_delete=False):
        if not isinstance(incoming, list):
            return
        if allow_delete:
            self.actions = [dict(action) for action in incoming if isinstance(action, dict)]
        else:
            index_by_id = {action.get("id"): index for index, action in enumerate(self.actions)}
            for raw in incoming:
                if not isinstance(raw, dict):
                    continue
                action = dict(raw)
                action_id = action.get("id") or self.make_action_id(
                    action.get("name", ""), action.get("command", ""), action.get("deviceId") or action.get("targetDeviceId"),
                )
                action["id"] = action_id
                target_index = index_by_id.get(action_id)
                if target_index is None:
                    self.actions.append(action)
                    index_by_id[action_id] = len(self.actions) - 1
                else:
                    self.actions[target_index].update(action)
        self.model_manager.sync_actions(self.actions)

    def current_device_actions(self, device=None):
        device = device or self.current_device()
        device_id = device.get("id")
        return [
            action for action in self.actions
            if (action.get("deviceId") or action.get("targetDeviceId")) == device_id
        ]

    def current_action_summary(self):
        actions = self.current_device_actions()
        if not actions:
            return "当前设备动作：未配置"
        names = [action.get("name", "") for action in actions[:4]]
        return "当前设备动作：" + " / ".join(name for name in names if name)

    def make_action_id(self, name, command=None, device_id=None):
        command_base = "".join(ch.lower() for ch in (command or "") if ch.isascii() and (ch.isalnum() or ch == "_")).strip("_")
        name_base = "".join(ch.lower() for ch in (name or "") if ch.isascii() and ch.isalnum()).strip("_")
        if command_base == "custom_action":
            base = name_base or self.make_id(name, "act")
        else:
            base = command_base or name_base or self.make_id(name, "act")
        return "{}_{}".format(device_id, base) if device_id else base

    def add_device(self, name, device_type=None, zone=None):
        name = (name or "").strip()
        if not name:
            self.log("添加设备失败：设备名为空")
            return None
        index = self.find_device_index(name)
        if index >= 0 and self.devices[index].get("name") == name:
            device = self.devices[index]
            device["type"] = device_type or device.get("type") or self.guess_device_type(name)
            device["zone"] = zone or device.get("zone") or "AIoT新增"
            self.device_index = index
            self.log("更新设备: {} / {} / {}".format(device["name"], device["type"], device["zone"]))
        else:
            device = {
                "id": self.make_id(name, "dev"),
                "name": name,
                "type": device_type or self.guess_device_type(name),
                "zone": zone or "AIoT新增",
            }
            self.devices.append(device)
            self.device_index = len(self.devices) - 1
            self.log("添加设备: {} / {} / {}".format(device["name"], device["type"], device["zone"]))
        self.sync_config("添加设备：" + device.get("name", ""))
        return device

    def delete_device(self, name_or_id=None):
        index = self.find_device_index(name_or_id or "当前设备")
        if index < 0 or len(self.devices) <= 1:
            self.log("删除设备失败：未找到设备或至少需要保留一个设备")
            return None
        removed = self.devices.pop(index)
        removed_id = removed.get("id")
        before_count = len(self.actions)
        self.actions = [
            action for action in self.actions
            if (action.get("deviceId") or action.get("targetDeviceId")) != removed_id
        ]
        removed_action_count = before_count - len(self.actions)
        self.model_manager.remove_device(removed_id)
        if index == self.device_index:
            self.device_index = index if index < len(self.devices) else len(self.devices) - 1
        elif index < self.device_index:
            self.device_index -= 1
        if self.device_index < 0:
            self.device_index = 0
        detail = "，同步移除 {} 个专属动作".format(removed_action_count) if removed_action_count else ""
        self.log("删除设备: {}{}，当前设备: {}".format(removed.get("name"), detail, self.current_device().get("name")))
        self.sync_config("删除设备：" + removed.get("name", ""))
        return removed

    def add_action(self, name, command=None, description=None, device_id=None, device_name=None, sync=True):
        name = (name or "").strip()
        if not name:
            self.log("添加动作失败：动作名为空")
            return None
        if device_id:
            device = self.set_target_device(device_id) or self.current_device()
        else:
            device = self.current_device()
        device_id = device.get("id") if device else device_id
        device_name = device.get("name") if device else (device_name or "")
        action_command = command or self.guess_action_command(name)
        command_action, trigger_name = self.guess_command_action_binding(name, action_command)
        action_id_command = command_action or action_command
        action = {
            "id": self.make_action_id(name, action_id_command, device_id),
            "name": name,
            "command": action_command,
            "description": description or "设备专属指令",
            "deviceId": device_id,
            "targetDeviceId": device_id,
            "deviceName": device_name,
        }
        if command_action:
            action["commandAction"] = command_action
            action["triggerName"] = trigger_name
            action["triggerCommand"] = action_command
            action["isCustomTrigger"] = False
        for index, old in enumerate(self.actions):
            old_device_id = old.get("deviceId") or old.get("targetDeviceId") or ""
            same_scope = old_device_id == (device_id or "")
            if old.get("id") == action["id"] or (old.get("name") == name and same_scope):
                self.actions[index] = action
                self.model_manager.ensure_profile(action)
                self.model_manager.save()
                self.log("更新动作: {} -> {} / {}".format(device_name, action["name"], action["command"]))
                if sync:
                    self.sync_config("添加动作：" + action.get("name", ""))
                return action
        self.actions.append(action)
        self.model_manager.ensure_profile(action)
        self.model_manager.save()
        self.log("添加动作: {} -> {} / {}".format(device_name, action["name"], action["command"]))
        if sync:
            self.sync_config("添加动作：" + action.get("name", ""))
        return action

    def delete_action(self, name_or_id, device_id=None):
        key = (name_or_id or "").strip()
        if not key:
            self.log("删除动作失败：动作名为空")
            return None
        target_device_id = device_id or self.current_device().get("id")
        matches = []
        for index, action in enumerate(self.actions):
            if action.get("id") == key or action.get("name") == key or (key and key in action.get("name", "")):
                matches.append((index, action))
        if matches:
            selected_index, selected_action = matches[0]
            for index, action in matches:
                action_device_id = action.get("deviceId") or action.get("targetDeviceId") or ""
                if action_device_id == target_device_id:
                    selected_index, selected_action = index, action
                    break
            removed = self.actions.pop(selected_index)
            self.model_manager.remove_action(removed.get("id"))
            self.log("删除动作: {}".format(removed.get("name")))
            self.sync_config("同步配置")
            return removed
        self.log("删除动作失败：未找到 {}".format(key))
        return None

    def guess_command_action_binding(self, name, command):
        text = "{} {}".format(name or "", command or "")
        if command == "swing_up" or "开启" in text or "打开" in text:
            return "power_on", "上摆"
        if command == "swing_down" or "关闭" in text or "关掉" in text:
            return "power_off", "下摆"
        if command == "rotate_cw" or "调高" in text or "增大" in text or "升高" in text:
            return "value_up", "顺时针"
        if command == "rotate_ccw" or "调低" in text or "减小" in text or "降低" in text:
            return "value_down", "逆时针"
        return "", ""

    def guess_action_command(self, name):
        if "速冻" in name:
            return "fridge_quick_freeze"
        if "打开" in name or "开启" in name:
            return "swing_up"
        if "关闭" in name:
            return "swing_down"
        if "调高" in name or "增大" in name:
            return "rotate_cw"
        if "调低" in name or "降低" in name:
            return "rotate_ccw"
        if "场景" in name or "观影" in name:
            return "flip_scene"
        return "custom_action"

    def clear_pending(self):
        count = 0
        while True:
            try:
                self.commands.get_nowait()
                count += 1
            except queue.Empty:
                break
        self.log("已清空待发送队列: {} 条".format(count))

    def start_closed_loop_demo(self):
        with self.demo_lock:
            if self.demo_running:
                self.log("AI闭环演示已在运行，已忽略重复触发")
                return {"running": True, "ignored": True}
            self.demo_running = True

        def worker():
            steps = [
                ("reset_state", "闭环 1/8 · 初始状态", 96, {
                    "demoFlow": True, "demoStage": "reset", "demoStep": 1, "demoTotal": 8,
                    "demoExplain": "设备全部复位为关闭，保证演示从可复现状态开始。",
                }),
                ("calibrate_space", "闭环 2/8 · 空间校准", 94, {
                    "demoFlow": True, "demoStage": "space_calibration", "demoStep": 2, "demoTotal": 8,
                    "demoExplain": "建立腕部指向坐标系，为候选设备选择提供空间基准。",
                }),
                ("point_next", "闭环 3/8 · 目标锁定", 90, {
                    "demoFlow": True, "demoStage": "space_lock", "demoStep": 3, "demoTotal": 8,
                    "demoExplain": "抬腕指向切换并锁定当前候选设备。",
                }),
                ("sensor_sample", "闭环 4/8 · 多模态采样", 88, {
                    "demoFlow": True, "demoStage": "feature_fusion", "demoStep": 4, "demoTotal": 8,
                    "sensorSummary": "EMG: 0.58/0.42/0.20/0.16 · ACC: 0.8/9.3/2.1 · GYRO: 0.15/-0.08/1.20",
                    "demoExplain": "PC Mock 模拟肌电与 IMU 窗口，后续可替换为真实传感器数据入口。",
                }),
                ("low_confidence_test", "闭环 5/8 · 误触拦截", 52, {
                    "demoFlow": True, "demoStage": "safety_reject", "demoStep": 5, "demoTotal": 8,
                    "demoExplain": "低置信度结果被安全门控拦截，避免误触发设备。",
                }),
                ("swing_up", "闭环 6/8 · 可信开启", 91, {
                    "demoFlow": True, "demoStage": "device_execute", "demoStep": 6, "demoTotal": 8,
                    "demoExplain": "融合识别通过阈值后，只控制当前空间锁定设备。",
                }),
                ("rotate_cw", "闭环 7/8 · 连续调节", 93, {
                    "demoFlow": True, "demoStage": "continuous_control", "demoStep": 7, "demoTotal": 8,
                    "demoExplain": "顺时针动作进入连续调节，适合亮度、音量、温度等渐变量。",
                }),
                ("compose_scene", "闭环 8/8 · 场景联动", 95, {
                    "demoFlow": True, "demoStage": "scene_complete", "demoStep": 8, "demoTotal": 8,
                    "sceneKey": "movie", "sceneLabel": "观影",
                    "demoExplain": "翻腕/场景意图可扩展为多设备编排，展示米家联动潜力。",
                }),
            ]
            try:
                self.clear_pending()
                self.log("AI闭环演示启动：空间锁定 -> 多模态融合 -> 安全门控 -> 设备执行")
                for index, (command, label, confidence, extra) in enumerate(steps):
                    if command == "point_next":
                        with self.lock:
                            if self.devices:
                                self.device_index = (self.device_index + 1) % len(self.devices)
                                target = self.current_device()
                                extra["targetDeviceId"] = target.get("id")
                                extra["targetDeviceName"] = target.get("name")
                                extra["selectionVersion"] = int(time.time() * 1000)
                    self.enqueue(command, label, confidence=confidence, from_demo=True, extra=extra)
                    self.log("AI闭环演示步骤 {}: {} ({})".format(index + 1, label, command))
                    time.sleep(1.0)
                self.log("AI闭环演示完成")
            finally:
                with self.demo_lock:
                    self.demo_running = False

        threading.Thread(target=worker, daemon=True).start()
        return {"running": True, "ignored": False, "steps": 8}

    def set_operation_mode(self, mode):
        normalized = mode if mode in ("demo", "training", "inference") else "demo"
        self.settings["operationMode"] = normalized
        self.save_config()
        labels = {
            "demo": "演示模式",
            "training": "训练模式",
            "inference": "识别模式",
        }
        label = labels.get(normalized, "演示模式")
        self.log("运行模式切换: {}".format(label))
        return self.enqueue(
            "set_mode",
            label,
            confidence=96,
            extra={
                "mode": normalized,
                "settings": self.settings,
            },
        )

    def enqueue(self, command, label=None, accel=None, confidence=None, pipeline=None, from_demo=False, extra=None):
        with self.lock:
            self.seq += 1
            extra = extra or {}
            target_id = extra.get("targetDeviceId") or extra.get("deviceId")
            action_def = extra.get("actionDef") if isinstance(extra.get("actionDef"), dict) else {}
            if not target_id and action_def:
                target_id = action_def.get("deviceId") or action_def.get("targetDeviceId")
            if target_id:
                self.set_target_device(target_id)
            device = self.current_device()
            item = {
                "ok": True,
                "seq": self.seq,
                "eventId": "evt-{}-{}".format(self.seq, int(time.time() * 1000)),
                "command": command,
                "label": label or command,
                "targetDeviceId": device.get("id"),
                "targetDeviceName": device.get("name"),
                "accel": accel or self.mock_accel(command),
                "confidence": confidence if confidence is not None else self.default_confidence.get(command, 88),
                "pipeline": pipeline or self.pipeline_for(command),
                "timestamp": int(time.time() * 1000),
            }
            item.update(extra)
            item["targetDeviceId"] = item.get("targetDeviceId") or device.get("id")
            item["targetDeviceName"] = item.get("targetDeviceName") or device.get("name")
            if action_def:
                action_def["deviceId"] = action_def.get("deviceId") or item["targetDeviceId"]
                action_def["targetDeviceId"] = action_def.get("targetDeviceId") or item["targetDeviceId"]
                action_def["deviceName"] = action_def.get("deviceName") or item["targetDeviceName"]
                item["actionDef"] = action_def
            self.last_queued = item
            self.commands.put(item)
        if not from_demo:
            self.log("发送到 AIoT: {} ({})".format(item["label"], command))
        self.wake_watch_app()
        return item

    def sync_config(self, label="同步配置"):
        self.config_version += 1
        self.save_config()
        return self.enqueue(
            "sync_config",
            label,
            confidence=96,
            extra={
                "devices": self.devices,
                "actions": self.actions,
                "models": self.recognition_models(),
                "settings": self.settings,
                "configVersion": self.config_version,
            },
        )

    def sample_history(self, action_id, limit=10):
        profile = self.model_manager.get_profile(action_id) or {}
        samples = profile.get("samples", [])
        return samples[-limit:]

    def recognition_models(self):
        return self.model_manager.export_profiles()

    def model_summary(self, action_id):
        for model in self.recognition_models():
            if model.get("actionId") == action_id:
                return model
        return None

    def workflow_state(self, action_id=None):
        key = (action_id or "").strip()
        action = None
        if key:
            for candidate in self.actions:
                if candidate.get("id") == key or candidate.get("name") == key:
                    action = candidate
                    break
        else:
            action = self.resolve_training_action()
        if not action:
            return {
                "phase": "unconfigured",
                "label": "待配置动作",
                "sampleCount": 0,
                "minSamples": self.model_manager.min_samples,
                "modelStatus": "untrained",
            }
        model = self.model_summary(action.get("id")) or {}
        count = int(model.get("sampleCount", 0) or 0)
        minimum = int(model.get("minSamples", self.model_manager.min_samples) or self.model_manager.min_samples)
        status = model.get("status", "untrained")
        if status == "trained":
            phase = "inference_ready"
            label = "模型已训练，可识别"
        elif count >= minimum:
            phase = "training_ready"
            label = "采集完成，等待训练"
        elif count > 0:
            phase = "collecting"
            label = "正在采集样本"
        else:
            phase = "capture_ready"
            label = "等待采集样本"
        return {
            "phase": phase,
            "label": label,
            "actionId": action.get("id"),
            "actionName": action.get("name", ""),
            "deviceId": action.get("deviceId") or action.get("targetDeviceId"),
            "deviceName": action.get("deviceName", ""),
            "sampleCount": count,
            "minSamples": minimum,
            "modelStatus": status,
            "quality": model.get("quality", 0),
            "threshold": model.get("threshold", 80),
        }

    def resolve_training_action(self, action_id=None):
        key = (action_id or self.training_action_id or "").strip()
        if key:
            for action in self.actions:
                if action.get("id") == key or action.get("name") == key:
                    self.training_action_id = action.get("id", "")
                    self.set_target_device(action.get("deviceId") or action.get("targetDeviceId"))
                    return action
            return None
        actions = self.current_device_actions()
        if actions:
            self.training_action_id = actions[0].get("id", "")
            return actions[0]
        return None

    def prepare_training_session(self, action_id=None):
        action = self.resolve_training_action(action_id)
        if not action:
            self.log("准备采集失败：当前设备没有动作")
            return None
        workflow = self.workflow_state(action.get("id"))
        if workflow["phase"] == "inference_ready":
            self.log("采集不可用：{} 已训练，如需重新训练请先清空样本".format(action.get("name", "")))
            return None
        if workflow["phase"] == "training_ready":
            self.log("采集已完成：{} 已达到 {}/10，请开始训练".format(action.get("name", ""), workflow["sampleCount"]))
            return None
        self.log("等待人工采集: {} -> {}，当前第 {}/{} 组".format(
            action.get("deviceName", ""), action.get("name", ""),
            workflow["sampleCount"] + 1, workflow["minSamples"],
        ))
        return self.enqueue(
            "training_session",
            "等待PC人工采集：" + action.get("name", ""),
            confidence=96,
            extra={
                "targetDeviceId": action.get("deviceId"),
                "targetDeviceName": action.get("deviceName"),
                "actionId": action.get("id"),
                "actionDef": action,
                "model": self.model_summary(action.get("id")),
                "models": self.recognition_models(),
                "workflow": workflow,
            },
        )

    def capture_training_sample(self, action_id=None, window=None, source="pc_manual"):
        action = self.resolve_training_action(action_id)
        if not action:
            self.log("采集失败：当前设备没有可训练动作，请先添加动作")
            return None
        if not window:
            return self.prepare_training_session(action.get("id"))
        existing = self.model_summary(action.get("id"))
        before_count = int((existing or {}).get("sampleCount", 0) or 0)
        profile = self.model_manager.record_sample(action, window, source)
        self.last_manual_windows[action.get("id")] = window
        model = self.model_summary(action.get("id"))
        count = model.get("sampleCount", 0) if model else 0
        if before_count >= self.model_manager.min_samples or count <= before_count:
            self.log("采集已封存：{} 已达到 {}/{}，本次输入未写入".format(
                action.get("name", ""), count, self.model_manager.min_samples,
            ))
            return None
        workflow = self.workflow_state(action.get("id"))
        self.log("记录人工样本: {} -> {} / {}/{}".format(action.get("deviceName", ""), action.get("name", ""), count, self.model_manager.min_samples))
        return self.enqueue(
            "training_sample",
            "人工样本 {}/{}：{}".format(count, self.model_manager.min_samples, action.get("name", "")),
            confidence=min(96, 72 + count * 2),
            extra={
                "targetDeviceId": action.get("deviceId"),
                "targetDeviceName": action.get("deviceName"),
                "actionId": action.get("id"),
                "actionDef": action,
                "model": model,
                "models": self.recognition_models(),
                "workflow": workflow,
                "sensorSummary": {"source": source, "frames": len(window.get("frames", [])), "emgChannels": window.get("emgChannels", 4), "imuAxes": window.get("imuAxes", 9)},
            },
        )

    def train_action_model(self, action_id=None):
        action = self.resolve_training_action(action_id)
        if not action:
            self.log("训练失败：当前设备没有可训练动作")
            return None
        profile = self.model_manager.ensure_profile(action)
        if profile.get("status") == "trained":
            self.log("训练已完成：{} 已有可用模型，如需重训请先清空样本".format(action.get("name", "")))
            return None
        profile = self.model_manager.train(profile.get("actionId"))
        model = self.model_summary(action.get("id"))
        trained = profile.get("status") == "trained"
        workflow = self.workflow_state(action.get("id"))
        label = ("模型训练完成：" if trained else "样本不足：") + action.get("name", "")
        self.log("{} / 样本 {} / 质量 {}%".format(label, profile.get("sampleCount", 0), profile.get("quality", 0)))
        return self.enqueue(
            "model_update",
            label,
            confidence=profile.get("quality", 60),
            extra={
                "targetDeviceId": action.get("deviceId"),
                "targetDeviceName": action.get("deviceName"),
                "actionId": action.get("id"),
                "actionDef": action,
                "model": model,
                "models": self.recognition_models(),
                "workflow": workflow,
            },
        )

    def prepare_inference_session(self, action_id=None):
        action = self.resolve_training_action(action_id)
        if not action:
            self.log("识别准备失败：当前设备没有动作")
            return None
        workflow = self.workflow_state(action.get("id"))
        if workflow["phase"] != "inference_ready":
            self.log("识别准备失败：{}，请先完成 10 组采集并训练模型".format(workflow["label"]))
            return None
        self.log("等待实时输入: 请在 PC 端输入一组肌电+IMU 数据并点击识别")
        return self.enqueue(
            "inference_waiting",
            "等待PC实时数据：" + action.get("name", ""),
            confidence=96,
            extra={
                "targetDeviceId": action.get("deviceId"),
                "targetDeviceName": action.get("deviceName"),
                "actionId": action.get("id"),
                "actionDef": action,
                "model": self.model_summary(action.get("id")),
                "models": self.recognition_models(),
                "workflow": workflow,
            },
        )

    def infer_action(self, action_id=None, window=None, source="pc_manual_realtime"):
        action = self.resolve_training_action(action_id)
        if not action:
            self.log("识别失败：当前设备没有可测试动作")
            return None
        if not window:
            return self.prepare_inference_session(action.get("id"))
        model = self.model_summary(action.get("id")) or {}
        if model.get("status") != "trained":
            self.log("识别被阻止：{} 尚未完成 10 组采集和模型训练".format(action.get("name", "")))
            return None
        workflow = self.workflow_state(action.get("id"))
        self.last_manual_windows[action.get("id")] = window
        inference = self.model_manager.predict(window, action.get("deviceId"))
        best = inference.get("best") or {}
        best_action = None
        for candidate in self.actions:
            if candidate.get("id") == best.get("actionId"):
                best_action = candidate
                break
        accepted = bool(inference.get("accepted") and best_action)
        label = ("AI识别通过：" + best.get("actionName", "")) if accepted else "AI识别未通过"
        self.log("{} / 置信度 {}% / 间隔 {}%".format(label, best.get("confidence", 0), inference.get("margin", 0)))
        return self.enqueue(
            "multimodal_inference",
            label,
            confidence=best.get("confidence", 0),
            extra={
                "targetDeviceId": best.get("deviceId") or action.get("deviceId"),
                "targetDeviceName": best.get("deviceName") or action.get("deviceName"),
                "actionId": best.get("actionId") or action.get("id"),
                "actionDef": best_action or action,
                "inference": inference,
                "predictions": inference.get("ranking", []),
                "models": self.recognition_models(),
                "workflow": workflow,
                "sensorSummary": {"source": source, "frames": len(window.get("frames", [])), "emgChannels": window.get("emgChannels", 4), "imuAxes": window.get("imuAxes", 9)},
            },
        )

    def clear_training_samples(self, action_id=None):
        action = self.resolve_training_action(action_id)
        if not action:
            return None
        profile = self.model_manager.clear_samples(action.get("id"))
        self.last_manual_windows.pop(action.get("id"), None)
        self.log("已清空训练样本：{}".format(action.get("name", "")))
        self.sync_models("训练样本已清空：" + action.get("name", ""))
        return profile

    def sync_models(self, label="同步 AI 模型"):
        workflow_states = []
        for action in self.actions:
            workflow_states.append(self.workflow_state(action.get("id")))
        return self.enqueue(
            "sync_models",
            label,
            confidence=96,
            extra={
                "devices": self.devices,
                "actions": self.actions,
                "models": self.recognition_models(),
                "workflowStates": workflow_states,
            },
        )

    def handle_multimodal_request(self, payload):
        request = payload.get("request") or payload.get("mode") or "infer"
        action_id = payload.get("actionId")
        if request in ("capture", "train_sample", "training"):
            return self.prepare_training_session(action_id)
        if request in ("train", "fit", "model_train"):
            return self.train_action_model(action_id)
        if request in ("sync", "sync_models"):
            return self.sync_models()
        return self.prepare_inference_session(action_id)

    def handle_sensor_window(self, payload):
        mode = payload.get("mode") or "infer"
        action_id = payload.get("actionId")
        window = payload.get("window") if isinstance(payload.get("window"), dict) else payload
        source = payload.get("source") or "external_sensor"
        if mode in ("capture", "train_sample", "training"):
            return self.capture_training_sample(action_id, window, source)
        if mode in ("train", "fit"):
            return self.train_action_model(action_id)
        return self.infer_action(action_id, window, source)

    def reset_state(self):
        self.device_index = 0
        return self.enqueue(
            "reset_state",
            "同步初始状态",
            accel={"x": 0.0, "y": 0.2, "z": 9.8},
            extra={
                "devices": self.devices,
                "actions": self.actions,
                "models": self.recognition_models(),
                "settings": self.settings,
                "mode": self.settings.get("operationMode", "demo"),
            },
        )

    def next_command(self):
        self.last_poll_at = time.time()
        try:
            item = self.commands.get_nowait()
            self.last_delivered = item
            response = dict(item)
            response.update(self.server_clock())
            return response
        except queue.Empty:
            time.sleep(0.35)
            response = {
                "ok": True,
                "seq": self.seq,
                "command": None,
                "label": "idle",
                "timestamp": int(time.time() * 1000),
            }
            response.update(self.server_clock())
            return response

    def server_clock(self):
        now = datetime.now().astimezone()
        offset = now.utcoffset()
        offset_minutes = int(offset.total_seconds() / 60) if offset else 0
        return {
            "serverTime": int(time.time() * 1000),
            "serverUtcOffsetMinutes": offset_minutes,
        }

    def wake_watch_app(self):
        def worker():
            try:
                subprocess.run(
                    [ADB, "-s", "emulator-5554", "shell", "am", "start", WATCH_PACKAGE],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                    check=False,
                )
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def record_watch_payload(self, payload):
        self.last_watch_payload = payload
        if not isinstance(payload, dict):
            self.log("收到手表回传: {}".format(payload))
            return
        payload_type = payload.get("type", "")
        if payload_type == "watch_input_command":
            self.last_watch_input = payload
            operation = payload.get("operation") or payload.get("sourceText") or ""
            allow_delete = operation in ("delete_device", "delete_action", "sync_config")
            if isinstance(payload.get("devices"), list) and payload.get("devices"):
                self.merge_devices(payload.get("devices"), allow_delete=allow_delete)
            if isinstance(payload.get("actions"), list):
                self.merge_actions(payload.get("actions"), allow_delete=allow_delete)
            if isinstance(payload.get("settings"), dict):
                self.settings.update(payload.get("settings"))
            if payload.get("targetDeviceId"):
                self.set_target_device(payload.get("targetDeviceId"))
            self.config_version = max(
                self.config_version + 1,
                int(payload.get("configVersion") or 0),
            )
            self.save_config()
            self.log("AIoT 本地输入同步: {} -> {} / {}".format(
                payload.get("inputSource", "AIoT"),
                payload.get("sourceText", ""),
                payload.get("label", ""),
            ))
            return
        if payload_type == "space_aiot_intent":
            detail = " -> {}".format(payload.get("value")) if payload.get("value", "") != "" else ""
            self.log("设备执行: {} -> {}{}".format(payload.get("deviceName", "AIoT"), payload.get("action", "unknown"), detail))
            return
        if payload_type == "pc_command_ack":
            detail = " / {}".format(payload.get("intentDetail")) if payload.get("intentDetail") else ""
            self.log("界面响应: {} -> {} -> {}{}".format(
                payload.get("label") or payload.get("command", "上位机命令"),
                payload.get("deviceName", "AIoT"),
                payload.get("intentTitle", "已响应"),
                detail,
            ))
            return
        self.log("收到手表回传: {}".format(payload))

    def parse_text_command(self, text, input_source="PC文本"):
        source = self.normalize_pinyin_text((text or "").strip())
        compact = source.replace("，", " ").replace(",", " ").replace(" ", "")
        if not compact:
            return None
        name = self.extract_after_prefix(compact, ["添加设备", "新增设备"])
        if name:
            self.add_device(name)
            return self.last_queued
        name = self.extract_after_prefix(compact, ["删除设备", "移除设备"])
        if name:
            removed = self.delete_device(name)
            return self.last_queued or {"ok": True, "deleted": removed}
        name = self.extract_after_prefix(compact, ["添加动作", "新增动作"])
        if name:
            self.add_action(name)
            return self.last_queued
        name = self.extract_after_prefix(compact, ["删除动作", "移除动作"])
        if name:
            self.delete_action(name)
            return self.last_queued
        self.sync_target_from_text(compact)
        if any(word in compact for word in ["打开", "开启", "启动"]):
            return self.enqueue("swing_up", "文本开启", extra={"sourceText": source, "inputSource": input_source})
        if any(word in compact for word in ["关闭", "关掉"]):
            return self.enqueue("swing_down", "文本关闭", extra={"sourceText": source, "inputSource": input_source})
        if any(word in compact for word in ["顺时针", "调高", "升高", "增大"]):
            return self.enqueue("rotate_cw", "文本调高", extra={"sourceText": source, "inputSource": input_source})
        if any(word in compact for word in ["逆时针", "调低", "降低", "减小"]):
            return self.enqueue("rotate_ccw", "文本调低", extra={"sourceText": source, "inputSource": input_source})
        if any(word in compact for word in ["观影", "睡眠", "专注", "离家", "场景"]):
            scene_key = "away" if "离家" in compact else "sleep" if "睡眠" in compact else "movie"
            return self.enqueue("compose_scene", "文本场景", confidence=95, extra={
                "sceneKey": scene_key,
                "sourceText": source,
                "inputSource": input_source,
            })
        return self.enqueue("custom_action", "文本指令", extra={"sourceText": source, "inputSource": input_source})

    def normalize_pinyin_text(self, text):
        compact = text.lower().replace(" ", "")
        mapping = {
            "tianjiashebeishouji": "添加设备手机",
            "tianjiashebeibingxiang": "添加设备冰箱",
            "tianjiashebeixiyiji": "添加设备洗衣机",
            "shanchushebeishouji": "删除设备手机",
            "shanchushebeibingxiang": "删除设备冰箱",
            "shanchushebeixiyiji": "删除设备洗衣机",
            "dakaibingxiang": "打开冰箱",
            "guanbibingxiang": "关闭冰箱",
            "dakaixiyiji": "打开洗衣机",
            "guanbixiyiji": "关闭洗衣机",
        }
        return mapping.get(compact, text)

    def pinyin_candidates(self, text, field="name"):
        key = (text or "").strip().lower().replace(" ", "")
        if not key:
            return []
        if field in ("1", "type", "deviceType"):
            type_words = [
                ("phone", "phone"), ("fridge", "fridge"), ("camera", "camera"),
                ("light", "light"), ("ac", "ac"), ("curtain", "curtain"),
                ("speaker", "speaker"), ("tv", "tv"), ("fan", "fan"),
                ("switch", "switch"), ("cleaner", "cleaner"),
            ]
            return [{"text": text, "value": value} for pinyin, value in type_words if key in pinyin][:8]
        result = self.library_pinyin_candidates(key)
        if key not in result:
            result.append(key)
        return [{"text": word, "value": word} for word in result[:32]]

    def library_pinyin_candidates(self, key):
        if not DefaultDagParams or not dag:
            return []
        parts = self.split_pinyin_key(key)
        if not parts:
            return []
        try:
            dag_params = DefaultDagParams()
            paths = dag(dag_params, parts, path_num=40)
        except Exception as error:
            self.log("拼音候选库调用失败: {}".format(error))
            return []
        result = []
        for item in paths:
            if isinstance(item.path, list):
                word = "".join(item.path)
            else:
                word = str(item.path)
            if word and word not in result:
                result.append(word)
        return result

    def split_pinyin_key(self, key):
        if not key:
            return []
        known = {
            "a", "ai", "an", "ang", "ao", "ba", "bai", "ban", "bang", "bao", "bei", "ben", "beng",
            "bi", "bian", "biao", "bie", "bin", "bing", "bo", "bu", "ca", "cai", "can", "cang",
            "cao", "ce", "cen", "ceng", "cha", "chai", "chan", "chang", "chao", "che", "chen",
            "cheng", "chi", "chong", "chou", "chu", "chuai", "chuan", "chuang", "chui", "chun",
            "chuo", "ci", "cong", "cou", "cu", "cuan", "cui", "cun", "cuo", "da", "dai", "dan",
            "dang", "dao", "de", "dei", "den", "deng", "di", "dia", "dian", "diao", "die", "ding",
            "diu", "dong", "dou", "du", "duan", "dui", "dun", "duo", "e", "ei", "en", "eng", "er",
            "fa", "fan", "fang", "fei", "fen", "feng", "fo", "fou", "fu", "ga", "gai", "gan",
            "gang", "gao", "ge", "gei", "gen", "geng", "gong", "gou", "gu", "gua", "guai", "guan",
            "guang", "gui", "gun", "guo", "ha", "hai", "han", "hang", "hao", "he", "hei", "hen",
            "heng", "hong", "hou", "hu", "hua", "huai", "huan", "huang", "hui", "hun", "huo",
            "ji", "jia", "jian", "jiang", "jiao", "jie", "jin", "jing", "jiong", "jiu", "ju",
            "juan", "jue", "jun", "ka", "kai", "kan", "kang", "kao", "ke", "ken", "keng", "kong",
            "kou", "ku", "kua", "kuai", "kuan", "kuang", "kui", "kun", "kuo", "la", "lai", "lan",
            "lang", "lao", "le", "lei", "leng", "li", "lia", "lian", "liang", "liao", "lie", "lin",
            "ling", "liu", "lo", "long", "lou", "lu", "luan", "lue", "lun", "luo", "lv", "ma",
            "mai", "man", "mang", "mao", "me", "mei", "men", "meng", "mi", "mian", "miao", "mie",
            "min", "ming", "miu", "mo", "mou", "mu", "na", "nai", "nan", "nang", "nao", "ne",
            "nei", "nen", "neng", "ni", "nian", "niang", "niao", "nie", "nin", "ning", "niu",
            "nong", "nou", "nu", "nuan", "nue", "nuo", "nv", "o", "ou", "pa", "pai", "pan",
            "pang", "pao", "pei", "pen", "peng", "pi", "pian", "piao", "pie", "pin", "ping",
            "po", "pou", "pu", "qi", "qia", "qian", "qiang", "qiao", "qie", "qin", "qing",
            "qiong", "qiu", "qu", "quan", "que", "qun", "ran", "rang", "rao", "re", "ren",
            "reng", "ri", "rong", "rou", "ru", "ruan", "rui", "run", "ruo", "sa", "sai", "san",
            "sang", "sao", "se", "sen", "seng", "sha", "shai", "shan", "shang", "shao", "she",
            "shen", "sheng", "shi", "shou", "shu", "shua", "shuai", "shuan", "shuang", "shui",
            "shun", "shuo", "si", "song", "sou", "su", "suan", "sui", "sun", "suo", "ta", "tai",
            "tan", "tang", "tao", "te", "teng", "ti", "tian", "tiao", "tie", "ting", "tong",
            "tou", "tu", "tuan", "tui", "tun", "tuo", "wa", "wai", "wan", "wang", "wei", "wen",
            "weng", "wo", "wu", "xi", "xia", "xian", "xiang", "xiao", "xie", "xin", "xing",
            "xiong", "xiu", "xu", "xuan", "xue", "xun", "ya", "yan", "yang", "yao", "ye", "yi",
            "yin", "ying", "yo", "yong", "you", "yu", "yuan", "yue", "yun", "za", "zai", "zan",
            "zang", "zao", "ze", "zei", "zen", "zeng", "zha", "zhai", "zhan", "zhang", "zhao",
            "zhe", "zhen", "zheng", "zhi", "zhong", "zhou", "zhu", "zhua", "zhuai", "zhuan",
            "zhuang", "zhui", "zhun", "zhuo", "zi", "zong", "zou", "zu", "zuan", "zui", "zun",
            "zuo",
        }
        result = []
        cursor = 0
        while cursor < len(key):
            found = ""
            max_size = min(6, len(key) - cursor)
            for size in range(max_size, 0, -1):
                part = key[cursor:cursor + size]
                if part in known:
                    found = part
                    break
            if not found:
                return [key]
            result.append(found)
            cursor += len(found)
        return result

    def extract_after_prefix(self, text, prefixes):
        for prefix in prefixes:
            if text.startswith(prefix):
                return text.replace(prefix, "", 1)
        return ""

    def sync_target_from_text(self, text):
        for index, device in enumerate(self.devices):
            name = device.get("name", "")
            if name and name in text:
                self.device_index = index
                return device
        return self.current_device()

    @staticmethod
    def pipeline_for(command):
        return {
            "point_next": "识别流程：采样 -> 空间指向 -> 候选设备锁定",
            "rotate_cw": "识别流程：采样 -> 圆周片段 -> 顺时针分类 -> 连续调高",
            "rotate_ccw": "识别流程：采样 -> 圆周片段 -> 逆时针分类 -> 连续调低",
            "swing_up": "识别流程：采样 -> 垂直摆动 -> 开启动作确认",
            "swing_down": "识别流程：采样 -> 垂直摆动 -> 关闭动作确认",
            "neutral_return": "识别流程：采样 -> 回正检测 -> 过滤完成",
            "flick_cancel": "识别流程：采样 -> 快速甩腕 -> 撤销最近动作",
            "flip_scene": "识别流程：采样 -> 翻腕检测 -> 多设备场景联动",
            "calibrate_space": "识别流程：空间采样 -> 方位聚类 -> 设备绑定",
            "low_confidence_test": "识别流程：采样 -> 疑似手势 -> 低置信过滤",
            "sensor_sample": "识别流程：连续采样 -> 分段缓存 -> 等待确认动作",
            "train_gesture": "学习流程：采样窗口 -> 特征提取 -> 个性化模板更新",
            "adaptive_match": "学习流程：当前手势 -> 模板相似度 -> 个性化匹配",
            "compose_scene": "场景流程：规则匹配 -> 多设备编排 -> 联动执行",
            "sync_config": "配置同步：设备库 + 动作库 -> 手表端",
            "training_sample": "学习流程：肌电+九轴采样 -> 特征提取 -> 样本入库",
            "model_update": "学习流程：样本集 -> 个性化模型训练 -> 阈值生成",
            "multimodal_inference": "AI流程：肌电+九轴融合 -> 多模型评分 -> 最高置信触发",
            "sync_models": "配置同步：设备库 + 动作库 + AI模型 -> 手表端",
            "training_session": "采集流程：选择设备动作 -> PC人工输入10组数据",
            "inference_waiting": "识别流程：等待PC实时肌电+IMU输入",
        }.get(command, "识别流程：采样 -> 分段 -> 手势分类 -> AIoT 执行")

    @staticmethod
    def mock_accel(command):
        samples = {
            "point_next": {"x": 1.6, "y": 8.8, "z": 2.1},
            "rotate_cw": {"x": 4.2, "y": 1.1, "z": 8.9},
            "rotate_ccw": {"x": -4.0, "y": 1.2, "z": 8.7},
            "swing_up": {"x": 0.8, "y": 11.6, "z": 3.2},
            "swing_down": {"x": 0.6, "y": -9.8, "z": 4.0},
            "flip_scene": {"x": -1.8, "y": -9.4, "z": -2.0},
            "neutral_return": {"x": 0.1, "y": 0.1, "z": 9.8},
            "flick_cancel": {"x": -7.2, "y": 2.4, "z": 6.4},
        }
        return samples.get(command, {"x": 0, "y": 0, "z": 9.8})


center = AiotCommandCenter()


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        return


class BridgeRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/aiot-command":
            self.send_json(center.next_command())
            return
        if path == "/pinyin-candidates":
            params = parse_qs(parsed_url.query)
            text = (params.get("text") or params.get("pinyin") or [""])[0]
            field = (params.get("field") or params.get("fieldIndex") or ["name"])[0]
            self.send_json({"ok": True, "candidates": center.pinyin_candidates(text, field)})
            return
        if path == "/health":
            workflow_states = []
            for action in center.actions:
                workflow_states.append(center.workflow_state(action.get("id")))
            self.send_json({
                "ok": True,
                "pending": center.commands.qsize(),
                "pcTarget": center.current_device(),
                "lastPollAt": center.last_poll_at,
                "lastQueued": center.last_queued,
                "lastDelivered": center.last_delivered,
                "lastWatchPayload": center.last_watch_payload,
                "lastWatchInput": center.last_watch_input,
                "devices": center.devices,
                "actions": center.actions,
                "models": center.recognition_models(),
                "workflowStates": workflow_states,
                "sensorWindowEndpoint": "http://127.0.0.1:{}/sensor-window".format(PORT),
            })
            return
        self.send_json({"ok": False, "error": "not_found"}, status=404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}

        if path not in ("/aiot-command", "/sensor-window", "/pinyin-candidates"):
            self.send_json({"ok": False, "error": "not_found"}, status=404)
            return

        if path == "/pinyin-candidates":
            text = payload.get("text") or payload.get("pinyin") or ""
            field = payload.get("field") or payload.get("fieldIndex") or "name"
            self.send_json({"ok": True, "candidates": center.pinyin_candidates(text, str(field))})
            return

        if path == "/sensor-window":
            try:
                item = center.handle_sensor_window(payload if isinstance(payload, dict) else {})
                if item is None:
                    workflow = center.workflow_state(payload.get("actionId"))
                    self.send_json({
                        "ok": False,
                        "error": "workflow_blocked",
                        "message": workflow.get("label", "当前流程未允许"),
                        "workflow": workflow,
                    })
                else:
                    self.send_json({"ok": True, "queued": item})
            except (ValueError, TypeError) as error:
                self.send_json({"ok": False, "error": str(error)}, status=400)
            return

        payload_type = payload.get("type") if isinstance(payload, dict) else None
        if payload_type == "multimodal_request":
            item = center.handle_multimodal_request(payload)
            if item is None:
                workflow = center.workflow_state(payload.get("actionId"))
                self.send_json({
                    "ok": False,
                    "error": "workflow_blocked",
                    "message": workflow.get("label", "当前流程未允许"),
                    "workflow": workflow,
                })
            else:
                self.send_json({"ok": True, "queued": item})
            return
        if payload_type == "sensor_window":
            item = center.handle_sensor_window(payload)
            self.send_json({"ok": True, "queued": item})
            return
        if payload_type in ("pc_command_ack", "space_aiot_intent", "watch_input_command"):
            center.record_watch_payload(payload)
            self.send_json({"ok": True, "received": True})
            return

        if isinstance(payload, dict) and payload.get("sourceText"):
            item = center.parse_text_command(payload.get("sourceText"), payload.get("inputSource", "MCU文本"))
            self.send_json({"ok": True, "parsed": item})
            return

        if isinstance(payload, dict) and payload.get("action") == "reset_state":
            self.send_json({"ok": True, "queued": center.reset_state()})
            return

        command = (payload.get("command") or payload.get("action")) if isinstance(payload, dict) else None
        if command:
            if command == "closed_loop_demo":
                self.send_json({"ok": True, "queued": center.start_closed_loop_demo()})
                return
            extra = {
                key: payload.get(key)
                for key in (
                    "devices", "actions", "actionDef", "configVersion", "sourceText", "inputSource",
                    "targetDeviceId", "targetDeviceName", "gestureKey", "trainingGesture", "sceneKey", "sceneLabel",
                    "models", "model", "actionId", "inference", "predictions", "sensorSummary",
                )
                if key in payload
            }
            if command == "point_next" and not payload.get("targetDeviceId"):
                with center.lock:
                    if center.devices:
                        center.device_index = (center.device_index + 1) % len(center.devices)
                        target = center.current_device()
                        extra["targetDeviceId"] = target.get("id")
                        extra["targetDeviceName"] = target.get("name")
                        extra["selectionVersion"] = int(time.time() * 1000)
            if command == "sync_config":
                if isinstance(payload.get("devices"), list) and payload.get("devices"):
                    center.merge_devices(payload.get("devices"), allow_delete=True)
                    center.device_index = 0
                if isinstance(payload.get("actions"), list):
                    center.merge_actions(payload.get("actions"), allow_delete=True)
            if payload.get("targetDeviceId"):
                center.set_target_device(payload.get("targetDeviceId"))
            item = center.enqueue(
                command,
                payload.get("label", command),
                payload.get("accel"),
                payload.get("confidence"),
                payload.get("pipeline"),
                extra=extra,
            )
            self.send_json({"ok": True, "queued": item})
            return

        center.record_watch_payload(payload)
        self.send_json({"ok": True, "received": True})

    def do_OPTIONS(self):
        self.send_response(204)
        self.add_headers(0)
        self.end_headers()

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.close_connection = True
        self.send_response(status)
        self.add_headers(len(body))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def add_headers(self, content_length):
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(content_length))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *args):
        return


def start_server():
    server = QuietThreadingHTTPServer((HOST, PORT), BridgeRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    center.log("HTTP 服务已启动: http://127.0.0.1:{}/aiot-command".format(PORT))
    center.log("模拟器可优先访问: http://10.0.2.2:{}/aiot-command".format(PORT))
    return server


class BridgeApp:
    def __init__(self):
        self.server = start_server()
        self.demo_jobs = []
        self.root = Tk()
        self.root.title("腕控空间 AIoT 上位机")
        self.root.geometry("1280x980")
        self.root.configure(bg="#10141c")
        self.status = Label(
            self.root,
            text="肌电 + 九轴 AI：选择设备动作，人工录入 10 组训练数据；训练后输入实时数据，由最高置信度模型触发。",
            bg="#10141c", fg="#d7deeb", font=("Microsoft YaHei UI", 11),
            anchor="w", padx=16, pady=12,
        )
        self.status.pack(side=TOP, fill="x")
        self.build_buttons()
        self.build_config_area()
        self.build_training_area()
        self.log_text = Text(
            self.root, height=9, bg="#080b10", fg="#d7deeb",
            insertbackground="#ffffff", relief="flat", font=("Consolas", 10),
        )
        self.log_text.pack(side=TOP, fill="both", expand=True, padx=14, pady=10)
        self.root.after(200, self.poll_logs)

    def build_buttons(self):
        area = Frame(self.root, bg="#10141c", padx=14, pady=4)
        area.pack(side=TOP, fill="x")
        rows = [Frame(area, bg="#10141c") for _ in range(4)]
        for row in rows:
            row.pack(side=TOP, fill="x")

        buttons = [
            (rows[0], "抬腕指向\n切换候选设备", "point_next", "抬腕指向", "#273041", None),
            (rows[0], "顺时针\n连续调高", "rotate_cw", "顺时针", "#1d5cff", None),
            (rows[0], "逆时针\n连续调低", "rotate_ccw", "逆时针", "#1d5cff", None),
            (rows[0], "上摆开启\n开启/打开", "swing_up", "上摆开启", "#2e7d63", None),
            (rows[1], "下摆关闭\n关闭/合上", "swing_down", "下摆关闭", "#6f4fb8", None),
            (rows[1], "回正过滤\n不触发控制", "neutral_return", "回正过滤", "#4d596b", None),
            (rows[1], "甩腕撤销\n撤销上一步", "flick_cancel", "甩腕撤销", "#c8465b", None),
            (rows[1], "翻腕场景\n切换空间场景", "flip_scene", "翻腕场景", "#2e7d63", None),
            (rows[2], "空间校准\n四点采集", "calibrate_space", "空间校准", "#2e6f7d", None),
            (rows[2], "误触测试\n低置信过滤", "low_confidence_test", "误触测试", "#a86b1d", 52),
            (rows[2], "弱顺时针\n疑似动作", "rotate_cw", "弱顺时针", "#7d5c2e", 58),
            (rows[2], "数据流采样\n只发一次", "sensor_sample", "数据流采样", "#b8952e", None),
            (rows[3], "训练转腕\n模板 1/3", "train_rotate", "训练转腕", "#2e6f7d", None),
            (rows[3], "训练上摆\n模板 1/3", "train_swing", "训练上摆", "#2e7d63", None),
            (rows[3], "训练翻腕\n模板 1/3", "train_flip", "训练翻腕", "#2e3a4d", None),
            (rows[3], "个性匹配\n相似度评估", "adaptive_match", "个性匹配", "#a86b1d", None),
            (rows[3], "观影编排\n多设备联动", "compose_movie", "观影编排", "#1d5cff", None),
            (rows[3], "离家编排\n一键全关", "compose_away", "离家编排", "#6f4fb8", None),
        ]
        for row, text, command, label, color, confidence in buttons:
            self.add_button(row, text, lambda c=command, l=label, p=confidence: self.send_single_command(c, l, p), color)

        utility = Frame(self.root, bg="#10141c", padx=14, pady=4)
        utility.pack(side=TOP, fill="x")
        self.add_button(utility, "一键演示流程", self.demo_sequence, "#f4c55f", fg="#10141c", width=13, height=2)
        self.add_button(utility, "同步初始状态", center.reset_state, "#2e7d63", width=13, height=2)
        self.add_button(utility, "清空待发送队列", center.clear_pending, "#2b3443", width=15, height=2)

    def build_config_area(self):
        frame = Frame(self.root, bg="#10141c", padx=14, pady=4)
        frame.pack(side=TOP, fill="x")
        self.device_name = StringVar(value="冰箱")
        self.device_type = StringVar(value="fridge")
        self.device_zone = StringVar(value="厨房")
        Label(frame, text="设备", bg="#10141c", fg="#d7deeb", font=("Microsoft YaHei UI", 10, "bold")).pack(side=LEFT, padx=6)
        Entry(frame, textvariable=self.device_name, width=12, font=("Microsoft YaHei UI", 11)).pack(side=LEFT, padx=4)
        Entry(frame, textvariable=self.device_type, width=14, font=("Microsoft YaHei UI", 11)).pack(side=LEFT, padx=4)
        Entry(frame, textvariable=self.device_zone, width=12, font=("Microsoft YaHei UI", 11)).pack(side=LEFT, padx=4)
        self.add_button(frame, "添加/更新设备", self.add_or_update_device, "#2e7d63", width=13, height=2)
        self.add_button(frame, "删除当前设备", self.delete_current_device, "#c8465b", width=12, height=2)
        self.add_button(frame, "同步配置", center.sync_config, "#2b3443", width=10, height=2)

        action_frame = Frame(self.root, bg="#10141c", padx=14, pady=4)
        action_frame.pack(side=TOP, fill="x")
        self.action_name = StringVar(value="冰箱速冻")
        self.action_command = StringVar(value="fridge_quick_freeze")
        self.action_summary = StringVar(value=center.current_action_summary())
        Label(action_frame, text="动作", bg="#10141c", fg="#d7deeb", font=("Microsoft YaHei UI", 10, "bold")).pack(side=LEFT, padx=6)
        Entry(action_frame, textvariable=self.action_name, width=16, font=("Microsoft YaHei UI", 11)).pack(side=LEFT, padx=4)
        Entry(action_frame, textvariable=self.action_command, width=22, font=("Microsoft YaHei UI", 11)).pack(side=LEFT, padx=4)
        self.add_button(action_frame, "添加/更新动作", self.add_or_update_action, "#2e6f7d", width=13, height=2)
        self.add_button(action_frame, "删除动作", self.delete_action, "#c8465b", width=10, height=2)
        self.add_button(action_frame, "执行动作", self.execute_action, "#1d5cff", width=10, height=2)

        summary_frame = Frame(self.root, bg="#10141c", padx=20, pady=0)
        summary_frame.pack(side=TOP, fill="x")
        Label(summary_frame, textvariable=self.action_summary, bg="#10141c", fg="#9eacc5", font=("Microsoft YaHei UI", 10), anchor="w").pack(side=LEFT, padx=6)

        text_frame = Frame(self.root, bg="#10141c", padx=14, pady=4)
        text_frame.pack(side=TOP, fill="x")
        self.text_input = StringVar(value="打开冰箱")
        Label(text_frame, text="文本输入", bg="#10141c", fg="#d7deeb", font=("Microsoft YaHei UI", 10, "bold")).pack(side=LEFT, padx=6)
        Entry(text_frame, textvariable=self.text_input, width=42, font=("Microsoft YaHei UI", 11)).pack(side=LEFT, padx=4)
        self.add_button(text_frame, "发送文本指令", self.send_text_command, "#2b3443", width=14, height=2)
        Label(
            self.root,
            text="接口: GET /aiot-command 由手表轮询取命令；POST /aiot-command 接收手表回传。MCU 后续可直接 POST JSON。",
            bg="#10141c", fg="#9eacc5", anchor="w", padx=16,
        ).pack(side=TOP, fill="x")

    def build_training_area(self):
        frame = Frame(self.root, bg="#0b1119", padx=14, pady=7)
        frame.pack(side=TOP, fill="x")
        action_row = Frame(frame, bg="#0b1119")
        action_row.pack(side=TOP, fill="x")
        prompt_row = Frame(frame, bg="#0b1119")
        prompt_row.pack(side=TOP, fill="x")
        input_row = Frame(frame, bg="#0b1119")
        input_row.pack(side=TOP, fill="x")
        status_row = Frame(frame, bg="#0b1119")
        status_row.pack(side=TOP, fill="x")
        self.training_action = StringVar(value="")
        self.training_reference = StringVar(value="请选择当前设备动作")
        self.manual_sample = StringVar(value="")
        self.training_status = StringVar(value="模型：等待动作")
        Label(action_row, text="肌电+九轴 AI", bg="#0b1119", fg="#61d394", font=("Microsoft YaHei UI", 11, "bold")).pack(side=LEFT, padx=6)
        Entry(action_row, textvariable=self.training_action, width=24, font=("Microsoft YaHei UI", 11)).pack(side=LEFT, padx=4)
        self.add_button(action_row, "选择当前动作", self.select_current_training_action, "#2b3443", width=12, height=2)
        self.add_button(action_row, "清空样本", self.clear_training_samples, "#c8465b", width=10, height=2)
        self.add_button(action_row, "同步模型", self.sync_ai_models, "#6f4fb8", width=10, height=2)
        Label(prompt_row, textvariable=self.training_reference, bg="#0b1119", fg="#f4c55f", font=("Microsoft YaHei UI", 10), anchor="w", justify=LEFT, wraplength=1220).pack(side=LEFT, fill="x", padx=6, pady=4)
        Label(input_row, text="数据", bg="#0b1119", fg="#d7deeb", font=("Microsoft YaHei UI", 10, "bold")).pack(side=LEFT, padx=6)
        Entry(input_row, textvariable=self.manual_sample, width=76, font=("Consolas", 10)).pack(side=LEFT, padx=4)
        self.add_button(input_row, "记录本次数据", self.capture_training_sample, "#2e6f7d", width=12, height=2)
        self.add_button(input_row, "训练模型", self.train_current_model, "#2e7d63", width=10, height=2)
        self.add_button(input_row, "识别并触发", self.simulate_ai_inference, "#1d5cff", width=11, height=2)
        Label(status_row, textvariable=self.training_status, bg="#0b1119", fg="#aeb9cc", font=("Microsoft YaHei UI", 10), anchor="w").pack(side=LEFT, padx=6, pady=3)
        Label(status_row, text="格式: e1,e2,e3,e4 | ax,ay,az | gx,gy,gz", bg="#0b1119", fg="#6f819d", font=("Consolas", 9), anchor="e").pack(side=LEFT, padx=18, pady=3)
        self.refresh_training_fields(force_reference=True)

    @staticmethod
    def format_manual_values(values):
        emg = values.get("emg", [0, 0, 0, 0])
        accel = values.get("accel", {})
        gyro = values.get("gyro", {})
        return "{:.3f},{:.3f},{:.3f},{:.3f} | {:.3f},{:.3f},{:.3f} | {:.3f},{:.3f},{:.3f}".format(
            emg[0], emg[1], emg[2], emg[3], accel.get("x", 0), accel.get("y", 0), accel.get("z", 9.8), gyro.get("x", 0), gyro.get("y", 0), gyro.get("z", 0)
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
        return {"emg": emg, "accel": {"x": accel[0], "y": accel[1], "z": accel[2]}, "gyro": {"x": gyro[0], "y": gyro[1], "z": gyro[2]}}

    def resolve_training_action(self):
        key = self.training_action.get().strip() if hasattr(self, "training_action") else ""
        action = center.resolve_training_action(key)
        if action and hasattr(self, "training_action"):
            self.training_action.set(action.get("name", action.get("id", "")))
        return action

    def select_current_training_action(self):
        actions = center.current_device_actions()
        if not actions:
            center.log("当前设备没有动作，请先添加开启、关闭或自定义动作")
            self.refresh_training_fields()
            return
        current_id = center.training_action_id
        index = 0
        for item_index, action in enumerate(actions):
            if action.get("id") == current_id:
                index = (item_index + 1) % len(actions)
                break
        center.training_action_id = actions[index].get("id", "")
        self.training_action.set(actions[index].get("name", ""))
        self.refresh_training_fields(force_reference=True)

    def build_manual_window(self, action):
        values = self.parse_manual_values(self.manual_sample.get())
        return center.model_manager.manual_window(action, values, "pc_manual")

    def capture_training_sample(self):
        action = self.resolve_training_action()
        if not action:
            return
        try:
            window = self.build_manual_window(action)
        except ValueError as error:
            center.log("数据录入失败：{}".format(error))
            return
        center.capture_training_sample(action.get("id"), window, "pc_manual")
        self.refresh_training_fields(force_reference=True)

    def train_current_model(self):
        action = self.resolve_training_action()
        if action:
            center.train_action_model(action.get("id"))
        self.refresh_training_fields()

    def simulate_ai_inference(self):
        action = self.resolve_training_action()
        if not action:
            return
        try:
            values = self.parse_manual_values(self.manual_sample.get())
            window = center.model_manager.manual_window(action, values, "pc_manual_realtime")
        except ValueError as error:
            center.log("实时数据错误：{}".format(error))
            return
        center.infer_action(action.get("id"), window, "pc_manual_realtime")
        self.refresh_training_fields()

    def clear_training_samples(self):
        action = self.resolve_training_action()
        if action:
            center.clear_training_samples(action.get("id"))
        self.refresh_training_fields(force_reference=True)

    def sync_ai_models(self):
        center.sync_models()
        self.refresh_training_fields()

    def refresh_training_fields(self, force_reference=False):
        if not hasattr(self, "training_status"):
            return
        action = center.resolve_training_action(self.training_action.get() if hasattr(self, "training_action") else "")
        if not action:
            self.training_status.set("当前设备：{} | 暂无可训练动作，请先添加动作".format(center.current_device().get("name", "")))
            self.training_reference.set("添加或修改动作后，选择该动作并按顺序录入 10 组数据。")
            return
        self.training_action.set(action.get("name", ""))
        model = center.model_summary(action.get("id")) or {}
        count = model.get("sampleCount", 0)
        minimum = model.get("minSamples", 10)
        status_map = {"untrained": "未训练", "collecting": "采集中", "ready": "可训练", "trained": "已训练"}
        status = status_map.get(model.get("status", "untrained"), model.get("status", "未训练"))
        self.training_status.set("设备：{} | 动作：{} | 样本：{}/{} | 模型：{} | 质量：{}% | 阈值：{}%".format(
            action.get("deviceName", ""), action.get("name", ""), count, minimum, status, model.get("quality", 0), model.get("threshold", 80)
        ))
        if model.get("status") == "trained":
            self.training_reference.set("模型已训练。现在输入一组实时数据，点击“识别并触发”；AI 会比较当前设备全部已训练动作。")
        elif count >= minimum:
            self.training_reference.set("10 组数据已采集完成，请点击“训练模型”。")
        else:
            reference = center.model_manager.reference_values(action, count)
            self.training_reference.set("第 {}/{} 组：完整做一次“{}”。按参考值附近输入，可有少量自然波动。".format(count + 1, minimum, action.get("name", "")))
            if force_reference or not self.manual_sample.get().strip():
                self.manual_sample.set(self.format_manual_values(reference))

    def add_button(self, parent, text, command, color, fg="#ffffff", width=12, height=3):
        button = Button(
            parent, text=text, command=command, bg=color, fg=fg,
            activebackground=color, activeforeground=fg,
            font=("Microsoft YaHei UI", 10, "bold"), relief="flat", width=width, height=height,
        )
        button.pack(side=LEFT, padx=6, pady=6)
        return button

    def add_or_update_device(self):
        device = center.add_device(self.device_name.get(), self.device_type.get(), self.device_zone.get())
        if device:
            self.refresh_device_fields()
            self.open_device_action_dialog(device)

    def delete_current_device(self):
        removed = center.delete_device(center.current_device().get("id"))
        if removed:
            self.refresh_device_fields()

    def add_or_update_action(self):
        action = center.add_action(self.action_name.get(), self.action_command.get(), "PC 上位机设备专属动作")
        if action:
            self.refresh_action_fields()

    def delete_action(self):
        removed = center.delete_action(self.action_name.get())
        if removed:
            self.refresh_action_fields()

    def execute_action(self):
        device = center.set_target_device(self.device_name.get()) or center.current_device()
        action = {
            "name": self.action_name.get(),
            "command": self.action_command.get(),
            "description": "PC 上位机动作",
            "deviceId": device.get("id"),
            "targetDeviceId": device.get("id"),
            "deviceName": device.get("name"),
        }
        center.enqueue(
            "custom_action",
            action["name"],
            extra={
                "targetDeviceId": device.get("id"),
                "targetDeviceName": device.get("name"),
                "actionDef": action,
            },
        )
        self.refresh_device_fields()

    def send_text_command(self):
        center.parse_text_command(self.text_input.get(), "PC文本")
        self.refresh_device_fields()

    def refresh_device_fields(self):
        device = center.current_device()
        self.device_name.set(device.get("name", ""))
        self.device_type.set(device.get("type", "switch"))
        self.device_zone.set(device.get("zone", "AIoT新增"))
        self.refresh_action_fields()

    def refresh_action_fields(self):
        actions = center.current_device_actions()
        if actions:
            self.action_name.set(actions[0].get("name", ""))
            self.action_command.set(actions[0].get("command", ""))
        self.action_summary.set(center.current_action_summary())
        self.refresh_training_fields()

    def open_device_action_dialog(self, device):
        dialog = Toplevel(self.root)
        dialog.title("配置设备动作 - " + device.get("name", ""))
        dialog.geometry("520x380")
        dialog.configure(bg="#10141c")
        dialog.transient(self.root)
        Label(
            dialog,
            text="为「{}」选择可用动作".format(device.get("name", "")),
            bg="#10141c", fg="#ffffff", font=("Microsoft YaHei UI", 14, "bold"),
            anchor="w", padx=18, pady=14,
        ).pack(side=TOP, fill="x")
        Label(
            dialog,
            text="默认动作库保持不变；这里新增的是当前设备的专属动作，会同步到 openvela 手表端。",
            bg="#10141c", fg="#9eacc5", font=("Microsoft YaHei UI", 10),
            anchor="w", padx=18,
        ).pack(side=TOP, fill="x")

        option_area = Frame(dialog, bg="#10141c", padx=18, pady=10)
        option_area.pack(side=TOP, fill="x")
        adjustable = device.get("type") in ("light", "ac", "speaker", "fridge", "fan", "tv")
        option_defs = [
            ("开启设备", device.get("name", "") + "开启", "swing_up", True),
            ("关闭设备", device.get("name", "") + "关闭", "swing_down", True),
            ("连续调高", device.get("name", "") + "调高", "rotate_cw", adjustable),
            ("连续调低", device.get("name", "") + "调低", "rotate_ccw", adjustable),
        ]
        options = []
        for label, action_name, command, checked in option_defs:
            var = BooleanVar(value=checked)
            Checkbutton(
                option_area, text="{}  ->  {}".format(label, command), variable=var,
                bg="#10141c", fg="#d7deeb", activebackground="#10141c", activeforeground="#ffffff",
                selectcolor="#273041", font=("Microsoft YaHei UI", 11), anchor="w",
            ).pack(side=TOP, fill="x", pady=4)
            options.append((var, action_name, command))

        custom_area = Frame(dialog, bg="#10141c", padx=18, pady=4)
        custom_area.pack(side=TOP, fill="x")
        custom_name = StringVar(value="")
        custom_command = StringVar(value="custom_action")
        Label(custom_area, text="自定义", bg="#10141c", fg="#d7deeb", font=("Microsoft YaHei UI", 10, "bold")).pack(side=LEFT, padx=4)
        Entry(custom_area, textvariable=custom_name, width=18, font=("Microsoft YaHei UI", 11)).pack(side=LEFT, padx=4)
        Entry(custom_area, textvariable=custom_command, width=18, font=("Microsoft YaHei UI", 11)).pack(side=LEFT, padx=4)

        button_area = Frame(dialog, bg="#10141c", padx=18, pady=14)
        button_area.pack(side=TOP, fill="x")

        def save_actions():
            added = []
            for var, action_name, command in options:
                if var.get():
                    added.append(center.add_action(
                        action_name, command, "设备创建向导添加",
                        device.get("id"), device.get("name"), sync=False,
                    ))
            if custom_name.get().strip():
                added.append(center.add_action(
                    custom_name.get().strip(), custom_command.get().strip() or "custom_action",
                    "设备创建向导自定义", device.get("id"), device.get("name"), sync=False,
                ))
            center.sync_config("设备动作已更新：" + device.get("name", ""))
            self.refresh_device_fields()
            self.refresh_training_fields()
            self.log_text.insert(END, "动作配置完成：{}，新增/更新 {} 个动作\n".format(device.get("name", ""), len([item for item in added if item])))
            self.log_text.see(END)
            dialog.destroy()

        self.add_button(button_area, "保存并同步", save_actions, "#2e7d63", width=12, height=2)
        self.add_button(button_area, "稍后配置", dialog.destroy, "#2b3443", width=10, height=2)

    def send_single_command(self, command, title, confidence=None):
        self.cancel_demo_jobs()
        if command == "point_next":
            with center.lock:
                if center.devices:
                    center.device_index = (center.device_index + 1) % len(center.devices)
                    target = center.current_device()
                else:
                    target = center.current_device()
            center.enqueue(
                "point_next",
                title,
                confidence=confidence,
                extra={
                    "targetDeviceId": target.get("id"),
                    "targetDeviceName": target.get("name"),
                },
            )
            self.refresh_device_fields()
            return
        if command == "sensor_sample":
            center.enqueue("sensor_sample", "数据流采样", accel={"x": 2.4, "y": 7.6, "z": 5.8}, confidence=84)
        elif command == "train_rotate":
            center.enqueue("train_gesture", "训练转腕", confidence=94, extra={"gestureKey": "rotate_cw", "trainingGesture": "顺时针"})
        elif command == "train_swing":
            center.enqueue("train_gesture", "训练上摆", confidence=94, extra={"gestureKey": "swing_up", "trainingGesture": "上摆"})
        elif command == "train_flip":
            center.enqueue("train_gesture", "训练翻腕", confidence=94, extra={"gestureKey": "flip_scene", "trainingGesture": "翻腕"})
        elif command == "compose_movie":
            center.enqueue("compose_scene", "观影编排", confidence=95, extra={"sceneKey": "movie", "sceneLabel": "观影"})
        elif command == "compose_away":
            center.enqueue("compose_scene", "离家编排", confidence=95, extra={"sceneKey": "away", "sceneLabel": "离家"})
        else:
            center.enqueue(command, title, confidence=confidence)

    def demo_sequence(self):
        self.cancel_demo_jobs()
        steps = [
            ("reset_state", "同步初始状态", None, {}),
            ("calibrate_space", "空间校准", None, {}),
            ("point_next", "抬腕指向", None, {}),
            ("rotate_cw", "顺时针", None, {}),
            ("low_confidence_test", "误触测试", 52, {}),
            ("neutral_return", "回正过滤", None, {}),
            ("flip_scene", "翻腕场景", None, {}),
            ("train_gesture", "训练转腕", 94, {"gestureKey": "rotate_cw"}),
            ("adaptive_match", "个性匹配", 95, {}),
            ("compose_scene", "观影编排", 95, {"sceneKey": "movie"}),
        ]
        for index, (command, label, confidence, extra) in enumerate(steps):
            job = self.root.after(
                index * 900,
                lambda c=command, l=label, p=confidence, e=extra: center.enqueue(c, l, confidence=p, from_demo=True, extra=e),
            )
            self.demo_jobs.append(job)

    def cancel_demo_jobs(self):
        while self.demo_jobs:
            job = self.demo_jobs.pop()
            try:
                self.root.after_cancel(job)
            except Exception:
                pass

    def poll_logs(self):
        while True:
            try:
                line = center.ui_events.get_nowait()
                self.log_text.insert(END, line + "\n")
                self.log_text.see(END)
            except queue.Empty:
                break
        self.refresh_training_fields()
        self.root.after(200, self.poll_logs)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    from modern_ui import ModernBridgeApp

    app = ModernBridgeApp(center, start_server)
    app.run()
