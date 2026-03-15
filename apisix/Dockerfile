ARG APISIX_BASE_IMAGE=apache/apisix:3.11.0-debian
FROM ${APISIX_BASE_IMAGE}

USER root

# Java와 envsubst 설치
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre gettext-base \
    && ln -s "/usr/lib/jvm/java-17-openjdk-$(dpkg --print-architecture)" /usr/lib/jvm/java-17-openjdk \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/render-apisix-config.sh /usr/local/bin/render-apisix-config.sh
RUN chmod +x /usr/local/bin/render-apisix-config.sh

# 환경 변수 설정
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk
ENV PATH="${JAVA_HOME}/bin:${PATH}"

ENTRYPOINT ["/usr/local/bin/render-apisix-config.sh"]
