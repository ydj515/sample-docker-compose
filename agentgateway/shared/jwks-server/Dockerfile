FROM node:22-bookworm-slim
WORKDIR /app
COPY --chown=node:node server.mjs server.test.mjs ./
RUN node --test server.test.mjs
USER node
CMD ["node", "server.mjs"]
