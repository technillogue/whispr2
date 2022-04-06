# FROM registry.gitlab.com/packaging/signal-cli/signal-cli-native:v0-10-4-1 as signal
# RUN signal-cli --version | tee /signal-version
# RUN mv /usr/bin/signal-cli-native /usr/bin/signal-cli

FROM ubuntu:hirsute as auxin
WORKDIR /app
RUN apt-get update && apt-get -yy install curl unzip
RUN curl -L --output auxin-cli.zip https://nightly.link/mobilecoinofficial/auxin/workflows/actions/feature%2Fmerge_json/auxin-cli.zip
RUN unzip auxin-cli.zip && chmod +x ./auxin-cli

FROM python:3.9 as libbuilder
WORKDIR /app
RUN pip install poetry
RUN python3.9 -m venv /app/venv 
COPY ./pyproject.toml ./poetry.lock /app/
RUN VIRTUAL_ENV=/app/venv poetry install --no-dev

FROM ubuntu:hirsute
WORKDIR /app
RUN mkdir -p /app/data
RUN apt-get update
RUN apt-get install -y python3.9 libfuse2
RUN apt-get clean autoclean && apt-get autoremove --yes && rm -rf /var/lib/{apt,dpkg,cache,log}/
COPY --from=auxin /app/auxin-cli /app/
COPY --from=libbuilder /app/venv/lib/python3.9/site-packages /app/
COPY .git/COMMIT_EDITMSG whispr.py /app/ 
ENTRYPOINT ["/usr/bin/python3.9", "/app/whispr.py"]
