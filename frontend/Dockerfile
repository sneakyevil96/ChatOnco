FROM node:22-alpine AS base

WORKDIR /workspace/frontend

COPY package*.json ./
RUN npm ci

COPY . .

FROM base AS development
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM base AS build
RUN npm run build

FROM nginx:1.28-alpine AS production
COPY --from=build /workspace/frontend/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
