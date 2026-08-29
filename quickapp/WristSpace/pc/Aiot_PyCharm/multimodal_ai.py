import json
import math
import os
import random
import time


FEATURE_NAMES = [
    "emg_mav_1", "emg_mav_2", "emg_mav_3", "emg_mav_4",
    "emg_rms_1", "emg_rms_2", "emg_rms_3", "emg_rms_4",
    "emg_wl_1", "emg_wl_2", "emg_wl_3", "emg_wl_4",
    "gyro_mean_x", "gyro_mean_y", "gyro_mean_z",
    "gyro_energy_x", "gyro_energy_y", "gyro_energy_z",
    "accel_delta_x", "accel_delta_y", "accel_delta_z",
]


COMMAND_SIGNATURES = {
    "swing_up": {"emg": [0.86, 0.54, 0.34, 0.24], "gyro": [0.15, 2.80, 0.35], "accel": [0.45, 3.60, -0.80]},
    "swing_down": {"emg": [0.70, 0.44, 0.68, 0.30], "gyro": [-0.10, -2.70, 0.25], "accel": [0.25, -3.90, -0.70]},
    "rotate_cw": {"emg": [0.46, 0.78, 0.36, 0.66], "gyro": [0.20, 0.10, 3.10], "accel": [1.55, 0.40, -0.20]},
    "rotate_ccw": {"emg": [0.58, 0.34, 0.76, 0.44], "gyro": [-0.20, 0.10, -3.05], "accel": [-1.55, 0.42, -0.20]},
    "flip_scene": {"emg": [0.64, 0.60, 0.56, 0.52], "gyro": [1.90, -1.55, 0.90], "accel": [-0.90, -2.10, -3.10]},
    "flick_cancel": {"emg": [0.92, 0.72, 0.48, 0.58], "gyro": [-3.10, 1.60, 2.20], "accel": [-3.20, 1.30, -1.50]},
}


class MultimodalModelManager:
    """Personalized EMG + IMU classifier with a hardware-neutral window protocol."""

    # MANUAL_TRAINING_V2
    def __init__(self, storage_path=None, min_samples=10):
        self.storage_path = storage_path or os.path.join(os.path.dirname(__file__), "aiot_multimodal_models.json")
        self.min_samples = min_samples
        self.profiles = {}
        self.load()

    def load(self):
        try:
            with open(self.storage_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                self.profiles = payload.get("profiles", {}) or {}
        except (OSError, ValueError, TypeError):
            self.profiles = {}

    def save(self):
        folder = os.path.dirname(self.storage_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        payload = {"version": 1, "updatedAt": int(time.time() * 1000), "profiles": self.profiles}
        with open(self.storage_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    @staticmethod
    def action_device_id(action):
        return (action or {}).get("deviceId") or (action or {}).get("targetDeviceId") or ""

    def ensure_profile(self, action):
        if not isinstance(action, dict) or not action.get("id"):
            return None
        action_id = action["id"]
        profile = self.profiles.get(action_id) or {
            "modelId": "model_" + action_id,
            "actionId": action_id,
            "deviceId": self.action_device_id(action),
            "deviceName": action.get("deviceName", ""),
            "actionName": action.get("name", action_id),
            "command": action.get("command", "custom_action"),
            "status": "untrained",
            "sampleCount": 0,
            "minSamples": self.min_samples,
            "threshold": 78,
            "quality": 0,
            "version": 0,
            "samples": [],
            "centroid": [],
            "scale": [],
        }
        profile["deviceId"] = self.action_device_id(action)
        profile["deviceName"] = action.get("deviceName", profile.get("deviceName", ""))
        profile["actionName"] = action.get("name", profile.get("actionName", action_id))
        profile["command"] = action.get("command", profile.get("command", "custom_action"))
        # A training session is intentionally fixed at ten manual samples.
        # Trim old profiles created by earlier builds so the UI and model use
        # the same closed collection window.
        if len(profile.get("samples", [])) > self.min_samples:
            profile["samples"] = profile.get("samples", [])[:self.min_samples]
        profile["sampleCount"] = len(profile.get("samples", []))
        profile["minSamples"] = self.min_samples
        self.profiles[action_id] = profile
        return profile

    def sync_actions(self, actions):
        valid_ids = set()
        for action in actions or []:
            if not self.action_device_id(action):
                continue
            profile = self.ensure_profile(action)
            if profile:
                valid_ids.add(profile["actionId"])
        for action_id in list(self.profiles):
            if action_id not in valid_ids:
                del self.profiles[action_id]
        self.save()

    def remove_action(self, action_id):
        if action_id in self.profiles:
            del self.profiles[action_id]
            self.save()

    def remove_device(self, device_id):
        for action_id in list(self.profiles):
            if self.profiles[action_id].get("deviceId") == device_id:
                del self.profiles[action_id]
        self.save()

    def get_profile(self, action_id):
        return self.profiles.get(action_id)

    def export_profiles(self):
        result = []
        for profile in self.profiles.values():
            result.append({
                "modelId": profile.get("modelId"),
                "actionId": profile.get("actionId"),
                "deviceId": profile.get("deviceId"),
                "deviceName": profile.get("deviceName"),
                "actionName": profile.get("actionName"),
                "command": profile.get("command"),
                "status": profile.get("status", "untrained"),
                "sampleCount": len(profile.get("samples", [])),
                "minSamples": self.min_samples,
                "threshold": profile.get("threshold", 78),
                "quality": profile.get("quality", 0),
                "version": profile.get("version", 0),
                "featureNames": FEATURE_NAMES,
                "centroid": profile.get("centroid", []),
                "scale": profile.get("scale", []),
            })
        return sorted(result, key=lambda item: (item.get("deviceName", ""), item.get("actionName", "")))

    def find_action(self, actions, action_id=None, device_id=None):
        candidates = []
        for action in actions or []:
            if not self.action_device_id(action):
                continue
            if action_id and action.get("id") == action_id:
                return action
            if not device_id or self.action_device_id(action) == device_id:
                candidates.append(action)
        return candidates[0] if candidates else None

    def mock_window(self, action, sample_index=0, source="pc_mock"):
        command = (action or {}).get("command", "custom_action")
        signature = COMMAND_SIGNATURES.get(command)
        if not signature:
            seed = sum(ord(ch) for ch in ((action or {}).get("id") or command))
            signature = {
                "emg": [0.35 + ((seed >> index) & 3) * 0.12 for index in range(4)],
                "gyro": [((seed % 7) - 3) * 0.42, (((seed // 7) % 7) - 3) * 0.38, (((seed // 49) % 7) - 3) * 0.44],
                "accel": [((seed % 5) - 2) * 0.55, (((seed // 5) % 5) - 2) * 0.52, -0.65],
            }
        seed_text = "{}:{}:{}".format((action or {}).get("id", command), sample_index, source)
        rng = random.Random(sum((index + 1) * ord(ch) for index, ch in enumerate(seed_text)))
        frames = []
        frame_count = 32
        for index in range(frame_count):
            phase = index / float(frame_count - 1)
            envelope = math.sin(math.pi * phase) ** 2
            emg = [max(0.0, base * envelope + rng.uniform(-0.035, 0.035)) for base in signature["emg"]]
            gyro = [base * envelope + rng.uniform(-0.10, 0.10) for base in signature["gyro"]]
            accel = [base * phase + rng.uniform(-0.08, 0.08) for base in signature["accel"]]
            accel[2] += 9.8
            frames.append({
                "timestamp": int(time.time() * 1000) + index * 20,
                "emg": [round(value, 5) for value in emg],
                "accel": {"x": round(accel[0], 5), "y": round(accel[1], 5), "z": round(accel[2], 5)},
                "gyro": {"x": round(gyro[0], 5), "y": round(gyro[1], 5), "z": round(gyro[2], 5)},
            })
        return {
            "schema": "space-aiot.multimodal-window.v1",
            "source": source,
            "sampleRateHz": 50,
            "emgChannels": 4,
            "imuAxes": 9,
            "deviceId": self.action_device_id(action),
            "actionId": (action or {}).get("id", ""),
            "frames": frames,
        }

    def reference_values(self, action, sample_index=0):
        command = (action or {}).get("command", "custom_action")
        signature = COMMAND_SIGNATURES.get(command)
        if not signature:
            seed = sum(ord(ch) for ch in ((action or {}).get("id") or command))
            signature = {
                "emg": [0.35 + ((seed >> index) & 3) * 0.12 for index in range(4)],
                "gyro": [((seed % 7) - 3) * 0.42, (((seed // 7) % 7) - 3) * 0.38, (((seed // 49) % 7) - 3) * 0.44],
                "accel": [((seed % 5) - 2) * 0.55, (((seed // 5) % 5) - 2) * 0.52, -0.65],
            }
        offsets = [-0.045, -0.030, -0.018, -0.008, 0.0, 0.010, 0.020, 0.032, 0.042, 0.015]
        offset = offsets[sample_index % len(offsets)]
        return {
            "emg": [round(max(0.02, value + offset * (index + 1) / 4.0), 3) for index, value in enumerate(signature["emg"])],
            "accel": {"x": round(signature["accel"][0] + offset, 3), "y": round(signature["accel"][1] - offset, 3), "z": round(9.8 + signature["accel"][2], 3)},
            "gyro": {"x": round(signature["gyro"][0] + offset, 3), "y": round(signature["gyro"][1] - offset, 3), "z": round(signature["gyro"][2] + offset, 3)},
        }

    def manual_window(self, action, values, source="pc_manual"):
        if not isinstance(values, dict):
            raise ValueError("manual sample is required")
        emg_peak = list(values.get("emg") or [])
        if len(emg_peak) != 4:
            raise ValueError("EMG requires 4 channels")
        accel_peak = values.get("accel") or {}
        gyro_peak = values.get("gyro") or {}
        frames = []
        frame_count = 32
        seed_text = "{}:{}".format((action or {}).get("id", "manual"), json.dumps(values, sort_keys=True))
        rng = random.Random(sum((index + 1) * ord(ch) for index, ch in enumerate(seed_text)))
        for index in range(frame_count):
            phase = index / float(frame_count - 1)
            envelope = math.sin(math.pi * phase) ** 2
            emg = [max(0.0, float(value) * envelope + rng.uniform(-0.012, 0.012)) for value in emg_peak]
            gyro = {axis: float(gyro_peak.get(axis, 0.0)) * envelope + rng.uniform(-0.035, 0.035) for axis in ("x", "y", "z")}
            accel = {axis: (float(accel_peak.get(axis, 0.0)) - (9.8 if axis == "z" else 0.0)) * phase + rng.uniform(-0.025, 0.025) + (9.8 if axis == "z" else 0.0) for axis in ("x", "y", "z")}
            frames.append({
                "timestamp": int(time.time() * 1000) + index * 20,
                "emg": [round(value, 5) for value in emg],
                "accel": {axis: round(value, 5) for axis, value in accel.items()},
                "gyro": {axis: round(value, 5) for axis, value in gyro.items()},
            })
        return {
            "schema": "space-aiot.multimodal-window.v1",
            "source": source,
            "sampleRateHz": 50,
            "emgChannels": 4,
            "imuAxes": 9,
            "deviceId": self.action_device_id(action),
            "actionId": (action or {}).get("id", ""),
            "frames": frames,
            "manualValues": values,
        }

    def clear_samples(self, action_id):
        profile = self.profiles.get(action_id)
        if not profile:
            return None
        profile["samples"] = []
        profile["sampleCount"] = 0
        profile["status"] = "untrained"
        profile["quality"] = 0
        profile["version"] = 0
        profile["centroid"] = []
        profile["scale"] = []
        self.save()
        return profile

    @staticmethod
    def _axis(frame, group, axis):
        value = (frame.get(group) or {}).get(axis, 0.0)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def extract_features(self, window):
        frames = (window or {}).get("frames") or []
        if not frames:
            raise ValueError("sensor window has no frames")
        channels = [[], [], [], []]
        for frame in frames:
            emg = frame.get("emg") or []
            for index in range(4):
                try:
                    channels[index].append(float(emg[index]))
                except (IndexError, TypeError, ValueError):
                    channels[index].append(0.0)
        features = []
        for values in channels:
            features.append(sum(abs(value) for value in values) / len(values))
        for values in channels:
            features.append(math.sqrt(sum(value * value for value in values) / len(values)))
        for values in channels:
            features.append(sum(abs(values[index] - values[index - 1]) for index in range(1, len(values))))
        for axis in ("x", "y", "z"):
            values = [self._axis(frame, "gyro", axis) for frame in frames]
            features.append(sum(values) / len(values))
        for axis in ("x", "y", "z"):
            values = [self._axis(frame, "gyro", axis) for frame in frames]
            features.append(sum(value * value for value in values) / len(values))
        for axis in ("x", "y", "z"):
            values = [self._axis(frame, "accel", axis) for frame in frames]
            features.append(values[-1] - values[0])
        return [round(value, 6) for value in features]

    def record_sample(self, action, window, source="pc_mock"):
        profile = self.ensure_profile(action)
        if not profile:
            raise ValueError("action is required")
        if len(profile.get("samples", [])) >= self.min_samples:
            profile["sampleCount"] = self.min_samples
            profile["status"] = "ready" if profile.get("status") != "trained" else "trained"
            self.save()
            return profile
        features = self.extract_features(window)
        profile.setdefault("samples", []).append({
            "source": source,
            "capturedAt": int(time.time() * 1000),
            "features": features,
            "manualValues": (window or {}).get("manualValues"),
        })
        if len(profile["samples"]) > self.min_samples:
            profile["samples"] = profile["samples"][:self.min_samples]
        profile["sampleCount"] = len(profile["samples"])
        profile["status"] = "ready" if profile["sampleCount"] >= self.min_samples else "collecting"
        self.save()
        return profile

    def train(self, action_id):
        profile = self.profiles.get(action_id)
        if not profile:
            raise ValueError("model profile not found")
        samples = [item.get("features", []) for item in profile.get("samples", []) if item.get("features")]
        if len(samples) < self.min_samples:
            profile["status"] = "collecting"
            self.save()
            return profile
        dimension = len(samples[0])
        centroid = [sum(sample[index] for sample in samples) / len(samples) for index in range(dimension)]
        scale = []
        for index in range(dimension):
            variance = sum((sample[index] - centroid[index]) ** 2 for sample in samples) / len(samples)
            scale.append(max(math.sqrt(variance), 0.035))
        profile["centroid"] = [round(value, 6) for value in centroid]
        profile["scale"] = [round(value, 6) for value in scale]
        profile["status"] = "trained"
        profile["quality"] = min(99, 70 + len(samples) * 2)
        profile["threshold"] = 80 if len(samples) < 15 else 83
        profile["version"] = int(profile.get("version", 0)) + 1
        profile["trainedAt"] = int(time.time() * 1000)
        self.save()
        return profile

    def predict(self, window, device_id=None):
        features = self.extract_features(window)
        ranking = []
        for profile in self.profiles.values():
            if profile.get("status") != "trained" or not profile.get("centroid"):
                continue
            if device_id and profile.get("deviceId") != device_id:
                continue
            centroid = profile["centroid"]
            scale = profile.get("scale") or [1.0] * len(centroid)
            dimension = min(len(features), len(centroid), len(scale))
            distance = math.sqrt(sum(((features[index] - centroid[index]) / max(scale[index], 0.035)) ** 2 for index in range(dimension)) / max(1, dimension))
            confidence = max(0.0, min(99.0, 100.0 - distance * 13.0))
            ranking.append({
                "modelId": profile.get("modelId"),
                "actionId": profile.get("actionId"),
                "actionName": profile.get("actionName"),
                "deviceId": profile.get("deviceId"),
                "deviceName": profile.get("deviceName"),
                "command": profile.get("command"),
                "confidence": round(confidence, 1),
                "threshold": profile.get("threshold", 78),
            })
        ranking.sort(key=lambda item: item["confidence"], reverse=True)
        best = ranking[0] if ranking else None
        second_confidence = ranking[1]["confidence"] if len(ranking) > 1 else 0.0
        accepted = bool(best and best["confidence"] >= best["threshold"] and best["confidence"] - second_confidence >= 4.0)
        return {
            "schema": "space-aiot.multimodal-inference.v1",
            "accepted": accepted,
            "best": best,
            "margin": round((best["confidence"] - second_confidence) if best else 0.0, 1),
            "ranking": ranking[:4],
            "features": features,
        }
