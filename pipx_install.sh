# 安装当前项目到隔离的 pipx 环境，便于全局调用 pydep 命令
# --editable：以可编辑模式安装，源码改动即时生效，无需重新安装
# --force：若已存在同名环境则先卸载再重装，避免版本残留
pipx install --editable . --force
