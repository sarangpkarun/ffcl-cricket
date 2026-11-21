FROM node:20-slim
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
CMD ["pnpm", "dev", "-H", "0.0.0.0"]
