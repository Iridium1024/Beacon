import Fastify, { type FastifyInstance, type RouteHandlerMethod, type RouteShorthandOptions } from "fastify";

export interface HttpRouteDefinition {
  method: "GET" | "POST" | "PUT" | "DELETE";
  path: string;
  handler: RouteHandlerMethod;
  options?: RouteShorthandOptions;
}

export interface HttpServer {
  registerRoute(route: HttpRouteDefinition): Promise<void>;
  start(): Promise<void>;
  raw(): FastifyInstance;
}

class FastifyHttpServer implements HttpServer {
  public constructor(
    private readonly server: FastifyInstance,
    private readonly host: string,
    private readonly port: number,
  ) {}

  public async registerRoute(route: HttpRouteDefinition): Promise<void> {
    this.server.route({
      method: route.method,
      url: route.path,
      handler: route.handler,
      ...(route.options ? { schema: route.options.schema } : {}),
    });
  }

  public async start(): Promise<void> {
    await this.server.listen({ host: this.host, port: this.port });
  }

  public raw(): FastifyInstance {
    return this.server;
  }
}

export const createHttpServer = (host: string, port: number): HttpServer => {
  const server = Fastify({
    logger: false,
  });

  return new FastifyHttpServer(server, host, port);
};
