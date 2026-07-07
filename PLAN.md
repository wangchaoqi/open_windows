# 优化计划

## 阶段一：日志 + 单测（基础能力）
预计 1-2 小时

- 日志到 `switcher_log.txt`，记录启动/停止/切换/异常
- 轮转保留 7 天，单文件最大 500KB
- unittest 覆盖 Config / 窗口过滤 / 空闲检测 / 自动停止

## 阶段二：键盘模拟（核心功能）
预计 2-3 小时

- 切到目标窗口后随机模拟 PageDown / Down 方向键
- SendInput API 实现，概率可配
- 新增配置项：input_sim_enabled / input_sim_chance

## 阶段三：中文界面
预计 1 小时

- 设置对话框和弹窗提示全部中文化

## 阶段四：托盘气泡提示
预计 1 小时

- 开始/停止/自动停止时弹出气泡通知
- Shell_NotifyIcon + NIF_INFO 实现

## 阶段五：打包 exe（最终交付）
预计 1-2 小时

- Nuitka 打包单文件 WindowSwitcher.exe
- 无控制台，含 tkinter，约 8-15 MB
- build.bat 一键编译脚本

## 执行顺序

```
一（日志+单测）→ 二（键盘模拟）→ 三（中文界面）→ 四（气泡提示）→ 五（打包exe）
```

每阶段验证通过再进入下一阶段。
