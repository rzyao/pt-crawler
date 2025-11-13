# 若在 ARM/受限环境遇到特定版本兼容问题，可改用 3.12：
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh && mkdir -p /config && cp /app/config.yaml /config/config.yaml || true
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "/app/docker-entrypoint.sh"]
