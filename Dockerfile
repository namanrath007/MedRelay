# MedRelay - one container: mock portal API + FHIR API (internal) + Streamlit dashboard (public)
# Built for Hugging Face Spaces (Docker SDK), works on any Docker host.
FROM python:3.11-slim

# Hugging Face runs containers as user 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .
# Rebuild the synthetic data + mock systems inside the image (deterministic: same seed as locally)
RUN python scripts/build_all.py && python scripts/smoke_test.py

EXPOSE 7860
CMD ["bash", "start.sh"]
