# 架构与发行边界

## 一个仓库，三个产品

三套产品共享基础模块，但从独立入口分别构建：

```text
XiaomiRemoteBridge  -> source/standalone/xiaomi_main.py
T1RemoteBridge      -> source/standalone/t1_main.py
V60PenBridge        -> source/standalone/v60_main.py
```

每个 PyInstaller spec 都显式排除另外两套硬件桥接。构建脚本还会反查生成的归档，发现跨设备模块、源码文件、授权模块或防破译构建内容时立即失败。

## 共享层

- `bridges/raw_input_bridge.py`：Windows Raw Input 事件。
- `bridges/physical_hotkey_monitor.py`：物理快捷键边沿监控。
- `bridges/native_audio.py`：T1 和 V60 的原生录音设备配置。
- `bridges/audio/`：仅小米包使用的 PCM 与虚拟音频路由。
- `runtime_launcher.py`：源码和冻结程序共用的内部角色启动方式。

## 可选统一中心

`source/remote_bridge_hub.py` 可以同时管理三套桥接，保留给源码用户和后续开发。官方的三个独立安装包不包含或依赖该入口。

## 公开仓库策略

- 第三方二进制不提交 Git，由校验锁定的脚本从官方地址获取。
- 来源不清晰的商品照片不参与构建。
- 真实设备地址、客户日志、私有路径和凭据不得进入仓库。
- 收费授权、设备绑定、防破译构建、云端与付款系统保持在仓库之外。
