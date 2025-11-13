# 若在 ARM/受限环境遇到特定版本兼容问题，可改用 3.12：
FROM python:3.13-slim
WORKDIR /pt-crawler
COPY requirements.txt /pt-crawler/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /pt-crawler/requirements.txt
COPY . /pt-crawler
RUN mkdir -p /config && cp /pt-crawler/config.yaml /config/config.yaml || true
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "pt-crawler:pt-crawler", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
