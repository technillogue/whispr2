FROM registry.gitlab.com/packaging/signal-cli/signal-cli-native:v0-12-8-1 as signal
USER root
#/RUN signal-cli --version | tee /signal-version
RUN mv /usr/bin/signal-cli-native /usr/bin/signal-cli

# FROM ubuntu:hirsute as auxin
# WORKDIR /app
# RUN apt-get update && apt-get -yy install curl unzip
# ENV A=1
# RUN curl -L --output auxin-cli.zip https://nightly.link/mobilecoinofficial/auxin/workflows/actions/main/auxin-cli.zip
# RUN unzip auxin-cli.zip && chmod +x ./auxin-cli

FROM python:3.11 as libbuilder
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/pip pip install poetry setuptools
RUN --mount=type=cache,target=/root/.cache/pip python3.11 -m venv /app/venv 
COPY ./pyproject.toml /app/
RUN --mount=type=cache,target=/root/.cache/pip VIRTUAL_ENV=/app/venv poetry install --no-dev

FROM ubuntu:jammy
WORKDIR /app
RUN mkdir -p /app/data
RUN apt-get update && apt-get install -y python3.11 ca-certificates libfuse2 \
  && apt-get clean autoclean && apt-get autoremove --yes && rm -rf /var/lib/{apt,dpkg,cache,log}/
COPY --from=signal /usr/bin/signal-cli /signal-cli.version /app/
COPY --from=signal /lib/x86_64-linux-gnu/libz.so.1 /lib64/
#COPY --from=auxin /app/auxin-cli /app/
COPY --from=libbuilder /app/venv/lib/python3.11/site-packages /app/
COPY .git/COMMIT_EDITMSG whispr.py /app/ 
ENV SIGNAL=signal
ENTRYPOINT ["/usr/bin/python3.11", "/app/whispr.py"]
