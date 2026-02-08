FROM node:20-alpine AS build

WORKDIR /app

COPY frontend-v2/package.json frontend-v2/package-lock.json ./
RUN npm ci

COPY frontend-v2/ ./

ARG VITE_API_KEY=df-internal-2024-workflow-key
ARG VITE_DEFAULT_LLM_API_URL=https://api.apiyi.com/v1
ARG VITE_LLM_API_URLS=https://api.apiyi.com/v1,http://b.apiyi.com:16888/v1,http://123.129.219.111:3000/v1
ARG VITE_API_BASE_URL=

ENV VITE_API_KEY=$VITE_API_KEY \
    VITE_DEFAULT_LLM_API_URL=$VITE_DEFAULT_LLM_API_URL \
    VITE_LLM_API_URLS=$VITE_LLM_API_URLS \
    VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

FROM nginx:alpine

COPY frontend-v2/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
