# 安装当前项目到隔离的 pipx 环境，便于全局调用 pydep 命令
# Install the current project into an isolated pipx environment so the pydep command is available globally.
# --editable：以可编辑模式安装，源码改动即时生效，无需重新安装
# --editable: install in editable mode, so source changes take effect immediately without reinstalling.
# --force：若已存在同名环境则先卸载再重装，避免版本残留
# --force: uninstall and reinstall the existing environment with the same name to avoid stale versions.
pipx install --editable . --force
