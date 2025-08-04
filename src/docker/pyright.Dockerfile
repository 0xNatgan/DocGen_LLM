# Use official Node.js image
FROM node:20-alpine

# Install pyright globally
RUN npm install -g pyright

# Set working directory
WORKDIR /workspace

CMD ["pyright-langserver", "--stdio"]