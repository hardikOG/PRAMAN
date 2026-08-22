# Dev-mode container: runs the Vite dev server directly. A production build
# (static export behind nginx) is not needed for this project's demo path —
# the console is always run locally alongside the rest of the stack.
FROM node:22-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
