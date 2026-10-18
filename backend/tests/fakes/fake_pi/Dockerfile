# Tiny image for the labelled fake Pi (tests only). Same entry contract as actron-pi: arguments are Pi's.
# Built by the test session: docker build -t actron-fake-pi:test backend/tests/fakes/fake_pi
FROM python:3.12.15-slim-bookworm
RUN pip install --no-cache-dir pytest==8.4.2 && useradd --create-home --uid 1000 pi
COPY fake_pi.py /fake_pi.py
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["python3", "/fake_pi.py"]
