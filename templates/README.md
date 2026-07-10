# templates/ 目录

**用途**: 配置文件模板

## 文件说明

| 文件 | 用途 |
|------|------|
| `AGENTS.md.template` | 会话配置模板 |
| `SOUL.md.template` | 身份与个性模板 |
| `USER.md.template` | 用户信息模板 |
| `TOOLS.md.template` | 工具配置模板 |
| `IDENTITY.md.template` | 身份标识模板 |
| `BOOTSTRAP.md.template` | 首次启动配置 |

## 使用方法

首次部署时，复制模板文件并填写：

```bash
cd /path/to/project

# 复制模板
cp templates/AGENTS.md.template AGENTS.md
cp templates/SOUL.md.template SOUL.md
cp templates/USER.md.template USER.md
cp templates/TOOLS.md.template TOOLS.md
cp templates/IDENTITY.md.template IDENTITY.md

# 编辑这些文件...
# 然后删除模板（可选）
rm -f *.template
```

**注意**: 这些模板文件用于新实例的初始化配置。
