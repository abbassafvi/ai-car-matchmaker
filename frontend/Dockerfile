FROM node:22-slim AS build
WORKDIR /app
# Copy the lockfile too and use `npm ci`: `npm install` without the
# lockfile re-resolves caret ranges at build time, so a rebuild could
# silently pull a different @a2ui/react than the one verified to work.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
