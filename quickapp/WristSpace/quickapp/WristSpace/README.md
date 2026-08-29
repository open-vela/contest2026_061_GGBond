# WristSpace QuickApp

该目录是 WristSpace 的 openvela 手表端快应用工程。

## 主要功能

- 矩形手表表盘适配。
- 空间候选设备展示与切换。
- 微手势指令执行反馈。
- 设备添加、删除与动作绑定。
- AI 学习、10 组样本采集、训练状态与识别结果展示。
- 通过 HTTP JSON 与 PC 上位机同步设备、动作、训练和识别状态。

## 运行

```powershell
cd E:\WristSpace\quickapp\WristSpace
npm install
npm run demo:rect
```

如需同时启动 PC 上位机：

```powershell
cd E:\WristSpace\quickapp\WristSpace
npm run demo:all
```
