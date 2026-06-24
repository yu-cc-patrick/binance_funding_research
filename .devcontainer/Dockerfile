# 资金费率极端事件研究项目 开发容器
# Python 3.9 + Claude Code + 中文字体(matplotlib 用)
FROM python:3.9-slim-bookworm

# 防火墙/基础工具 + 中文字体(matplotlib 绘图用,替代 macOS 的 Arial Unicode.ttf)
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
        iptables \
        ipset \
        dnsutils \
        sudo \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

# Node.js(Claude Code 运行时)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code

# 非 root 用户,免密 sudo 跑防火墙
ARG USERNAME=dev
RUN useradd -m -s /bin/bash $USERNAME \
    && echo "$USERNAME ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh" > /etc/sudoers.d/firewall \
    && chmod 0440 /etc/sudoers.d/firewall

# 防火墙脚本(root 拥有,用户只能执行不能改)
COPY init-firewall.sh /usr/local/bin/init-firewall.sh
RUN chmod 0755 /usr/local/bin/init-firewall.sh \
    && chown root:root /usr/local/bin/init-firewall.sh

USER $USERNAME
WORKDIR /workspace

# 项目依赖(matplotlib + python-docx)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --user -r /tmp/requirements.txt
ENV PATH="/home/dev/.local/bin:${PATH}"
