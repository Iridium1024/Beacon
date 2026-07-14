import { buildGateway } from "./index.js";

const start = async (): Promise<void> => {
  const runtime = await buildGateway();
  await runtime.server.start();
};

void start();
