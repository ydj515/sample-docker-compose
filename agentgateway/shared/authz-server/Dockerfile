FROM node:24.22.3-bookworm-slim
WORKDIR /app
COPY --chown=node:node server.mjs server.test.mjs ./
RUN node --test server.test.mjs
USER node
EXPOSE 9000
CMD ["node", "server.mjs"]
