FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/rocm6.2.4
RUN pip install --no-cache-dir -r requirements.txt
COPY hr_screening hr_screening
COPY data data
RUN useradd -u 10001 -m screening && mkdir runtime && chown screening:screening runtime
USER screening
ENV HR_HOST=0.0.0.0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
EXPOSE 8000
CMD ["python", "-m", "hr_screening"]
