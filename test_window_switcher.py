#!/usr/bin/env python3
"""窗口切换器单元测试 — 纯标准库，不依赖 tkinter。"""

import unittest
import json
import os
import sys
import tempfile
import struct
from pathlib import Path


# =============================================================================
# 从主模块复制的纯函数（避免 import 触发 tkinter 依赖）
# =============================================================================

def _generate_ico_bytes(size=32, r=76, g=175, b=80):
    """生成 .ico 字节数据。来源: window_switcher.pyw"""
    bih = struct.pack(
        "<IiiHHIIiiII",
        40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0,
    )
    pixels = bytearray()
    center = (size - 1) / 2.0
    radius = size / 2.0 - 1.5
    for y in range(size - 1, -1, -1):
        for x in range(size):
            dx = x - center
            dy = y - center
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= radius:
                pixels.extend([b, g, r, 255])
            else:
                pixels.extend([0, 0, 0, 0])
    and_row_bytes = (size + 7) // 8
    and_row_padded = (and_row_bytes + 3) // 4 * 4
    and_mask = bytearray(and_row_padded * size)
    image_data = bih + bytes(pixels) + bytes(and_mask)
    data_offset = 6 + 16
    entry = struct.pack(
        "<BBBBHHII",
        size if size < 256 else 0,
        size if size < 256 else 0,
        0, 0, 1, 32,
        len(image_data),
        data_offset,
    )
    header = struct.pack("<HHH", 0, 1, 1)
    return header + entry + image_data


class SimpleConfig:
    """Config 的纯逻辑复制（无文件 I/O 副作用）。"""

    DEFAULT = {
        "min_interval": 120,
        "max_interval": 300,
        "burst_enabled": True,
        "burst_chance": 0.15,
        "idle_threshold": 60,
        "auto_stop_time": "18:00",
    }

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.data = dict(self.DEFAULT)
        if self.path and self.path.exists():
            self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            for key in self.DEFAULT:
                if key in loaded:
                    self.data[key] = loaded[key]
        except (json.JSONDecodeError, IOError):
            pass

    def save(self):
        if self.path:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)


# =============================================================================
# 测试用例
# =============================================================================

class TestConfig(unittest.TestCase):
    """配置读写测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg_path = Path(self.tmpdir) / "test_config.json"

    def tearDown(self):
        if self.cfg_path.exists():
            self.cfg_path.unlink()
        os.rmdir(self.tmpdir)

    def test_defaults(self):
        cfg = SimpleConfig()
        self.assertEqual(cfg.data["min_interval"], 120)
        self.assertEqual(cfg.data["max_interval"], 300)
        self.assertTrue(cfg.data["burst_enabled"])
        self.assertEqual(cfg.data["burst_chance"], 0.15)

    def test_new_field_defaults(self):
        cfg = SimpleConfig()
        self.assertEqual(cfg.data["idle_threshold"], 60)
        self.assertEqual(cfg.data["auto_stop_time"], "18:00")

    def test_save_and_load_roundtrip(self):
        cfg = SimpleConfig(self.cfg_path)
        cfg.data["min_interval"] = 45
        cfg.data["auto_stop_time"] = "17:30"
        cfg.save()

        cfg2 = SimpleConfig(self.cfg_path)
        self.assertEqual(cfg2.data["min_interval"], 45)
        self.assertEqual(cfg2.data["auto_stop_time"], "17:30")

    def test_partial_update(self):
        """写入部分字段，其余保持默认。"""
        self.cfg_path.write_text(
            '{"min_interval": 999}', encoding="utf-8"
        )
        cfg = SimpleConfig(self.cfg_path)
        self.assertEqual(cfg.data["min_interval"], 999)
        self.assertEqual(cfg.data["max_interval"], 300)  # 未写入，保持默认

    def test_corrupted_json_fallback(self):
        self.cfg_path.write_text("{{{broken", encoding="utf-8")
        cfg = SimpleConfig(self.cfg_path)
        self.assertEqual(cfg.data["min_interval"], 120)

    def test_missing_file_uses_defaults(self):
        cfg = SimpleConfig(self.cfg_path)
        self.assertFalse(self.cfg_path.exists())
        self.assertEqual(cfg.data["min_interval"], 120)


class TestICOGeneration(unittest.TestCase):
    """ICO 图标生成测试。"""

    def test_valid_ico_structure(self):
        ico = _generate_ico_bytes(32, 76, 175, 80)
        self.assertIsInstance(ico, bytes)
        self.assertGreater(len(ico), 100)

        reserved, typ, count = struct.unpack_from("<HHH", ico, 0)
        self.assertEqual(reserved, 0)
        self.assertEqual(typ, 1)   # ICO type
        self.assertEqual(count, 1) # 1 image

    def test_total_size_matches_calculation(self):
        for size in (16, 32, 48):
            ico = _generate_ico_bytes(size, 0, 0, 0)
            and_row = (size + 7) // 8
            and_row_padded = (and_row + 3) // 4 * 4  # 4 字节对齐
            expected = 6 + 16 + 40 + size * size * 4 + and_row_padded * size
            self.assertEqual(len(ico), expected,
                             f"Size mismatch for {size}x{size}")

    def test_different_sizes(self):
        for size in (16, 32, 48):
            ico = _generate_ico_bytes(size, 255, 0, 0)
            self.assertIsInstance(ico, bytes)

    def test_different_colors(self):
        for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 128)):
            ico = _generate_ico_bytes(32, *color)
            self.assertIsInstance(ico, bytes)

    def test_32bit_bpp(self):
        """验证 bpp 字段为 32。"""
        ico = _generate_ico_bytes(32, 100, 100, 100)
        # 目录项偏移 6 bytes header, bpp 在 entry 偏移 6
        bpp = struct.unpack_from("<H", ico, 6 + 6)[0]
        self.assertEqual(bpp, 32)


class TestAutoStopTime(unittest.TestCase):
    """自动停止时间解析测试。"""

    @staticmethod
    def _parse(time_str):
        """模拟 _check_auto_stop 中的解析逻辑。"""
        h, m = map(int, time_str.strip().split(":"))
        from datetime import datetime
        return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)

    def test_standard_times(self):
        test_cases = [
            ("18:00", 18, 0),
            ("09:30", 9, 30),
            ("00:00", 0, 0),
            ("23:59", 23, 59),
        ]
        for time_str, expected_h, expected_m in test_cases:
            t = self._parse(time_str)
            self.assertEqual(t.hour, expected_h,
                             f"Hour mismatch for {time_str}")
            self.assertEqual(t.minute, expected_m,
                             f"Minute mismatch for {time_str}")

    def test_invalid_formats(self):
        invalid = ["abc", "25:00", "18:00:00", "18:xx", "", ":"]
        for bad in invalid:
            with self.assertRaises((ValueError, Exception),
                                   msg=f"Should raise for '{bad}'"):
                self._parse(bad)


class TestConfigEdgeCases(unittest.TestCase):
    """配置边界条件测试。"""

    def test_empty_json_object(self):
        """空 JSON 对象不覆盖默认值。"""
        tmp = tempfile.mkdtemp()
        try:
            path = Path(tmp) / "empty.json"
            path.write_text("{}", encoding="utf-8")
            cfg = SimpleConfig(path)
            self.assertEqual(cfg.data["min_interval"], 120)
        finally:
            path.unlink()
            os.rmdir(tmp)

    def test_extra_keys_ignored(self):
        """JSON 中多余的键不影响加载。"""
        tmp = tempfile.mkdtemp()
        try:
            path = Path(tmp) / "extra.json"
            path.write_text('{"unknown_key": 123, "min_interval": 50}',
                            encoding="utf-8")
            cfg = SimpleConfig(path)
            self.assertEqual(cfg.data["min_interval"], 50)
            self.assertNotIn("unknown_key", cfg.data)
        finally:
            path.unlink()
            os.rmdir(tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
