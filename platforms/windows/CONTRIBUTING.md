# 贡献指南

感谢你改进遥控器中心。

## 开始之前

1. 先搜索现有 Issue，避免重复提交。
2. 一个 Pull Request 只解决一个明确问题。
3. 不要提交真实设备地址、客户日志、账号、密钥、付款信息、本机绝对路径或第三方二进制。
4. 不要添加收费授权、设备绑定、防破译构建或私有服务依赖。
5. 涉及按键、麦克风或音频会话的修改，需要说明实际测试设备和验证结果。

## 本地检查

```powershell
.\scripts\check-public-boundary.ps1
python -m compileall -q source
python -m unittest discover -s tests -p "test_*.py"
```

构建安装器前还需安装 `requirements-dev.txt` 和 Inno Setup 6。构建脚本会按固定校验值获取第三方资源；请勿把下载的二进制提交到 Git。

## 提交说明

Pull Request 中请写清问题、改动、影响范围和验证方式。小米、T1、V60 三套桥接相互独立；修改一套设备时，确认没有把其他设备模块带进对应安装包。
