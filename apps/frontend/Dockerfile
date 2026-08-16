FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY apps/frontend/package.json ./
RUN npm install
COPY apps/frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY apps/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
