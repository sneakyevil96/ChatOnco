FROM node:22-alpine AS base

WORKDIR /workspace/frontend

COPY package*.json ./
RUN npm install

COPY . .

FROM base AS development
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM base AS build
RUN npm run build

