# docker build -t ssms-web ssms/web
FROM node:20.18-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build && npm run size

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
ENV SSMS_TRUSTED_PROXY=172.31.250.10 SSMS_RESOLVER=127.0.0.11
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
