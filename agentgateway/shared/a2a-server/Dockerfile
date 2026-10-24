FROM node:22-bookworm-slim
WORKDIR /app
COPY --chown=node:node server.mjs server.test.mjs ./
RUN node --test server.test.mjs
USER node
ENV PORT=3010
EXPOSE 3010
CMD ["node", "server.mjs"]
