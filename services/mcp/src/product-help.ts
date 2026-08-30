import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { z } from "zod";


type Capability = {
  capability_id: string;
  name: string;
  route_id: string;
  audience: "USER" | "ADMIN";
  purpose: string;
  prerequisites: string[];
  support: string[];
  limitations: string[];
  keywords?: string[];
};

type CapabilityCatalog = {
  schema_version: "product-capability-catalog.v1";
  catalog_version: string;
  capabilities: Capability[];
};

export const productHelpInputSchema = z.object({
  query: z.string().trim().min(1).max(120),
  capability_id: z.string().trim().min(1).max(80).optional(),
  include_admin: z.boolean().optional().default(false),
}).strict();

export type ProductHelpInput = z.infer<typeof productHelpInputSchema>;

let cachedCatalog: CapabilityCatalog | undefined;

function loadCatalog(): CapabilityCatalog {
  if (cachedCatalog) return cachedCatalog;
  const path = resolve(process.env.BYQ_PRODUCT_CAPABILITY_CATALOG ?? "/app/product-capability-catalog.v1.json");
  const value = JSON.parse(readFileSync(path, "utf-8")) as CapabilityCatalog;
  if (value.schema_version !== "product-capability-catalog.v1" || !Array.isArray(value.capabilities)) {
    throw new Error("product capability catalog is invalid");
  }
  cachedCatalog = value;
  return value;
}

function searchable(capability: Capability): string {
  return [
    capability.capability_id,
    capability.name,
    capability.route_id,
    capability.purpose,
    ...(capability.keywords ?? []),
  ].join(" ").toLocaleLowerCase("zh-CN");
}

function terms(query: string): string[] {
  const normalized = query.trim().toLocaleLowerCase("zh-CN");
  const split = normalized.split(/[\s,，。！？?、/]+/u).filter((item) => item.length >= 2);
  return [...new Set([normalized, ...split])];
}

function matchScore(capability: Capability, query: string, queryTerms: string[]): number {
  const normalized = query.trim().toLocaleLowerCase("zh-CN");
  const catalogueTerms = [capability.name, ...(capability.keywords ?? [])]
    .map((item) => item.toLocaleLowerCase("zh-CN"));
  const direct = catalogueTerms.reduce(
    (score, term) => score + (normalized.includes(term) ? term.length * 2 : 0),
    0,
  );
  return direct + queryTerms.reduce(
    (score, term) => score + (searchable(capability).includes(term) ? term.length : 0),
    0,
  );
}

export function queryProductHelp(input: unknown, suppliedCatalog?: CapabilityCatalog) {
  const request = productHelpInputSchema.parse(input);
  const catalog = suppliedCatalog ?? loadCatalog();
  const queryTerms = terms(request.query);
  const matches = catalog.capabilities
    .filter((item) => request.include_admin || item.audience !== "ADMIN")
    .filter((item) => !request.capability_id || item.capability_id === request.capability_id)
    .map((item) => ({
      item,
      score: matchScore(item, request.query, queryTerms),
    }))
    .filter(({ score }) => score > 0 || Boolean(request.capability_id))
    .sort((left, right) => right.score - left.score || left.item.capability_id.localeCompare(right.item.capability_id))
    .slice(0, 5)
    .map(({ item }) => ({
      capability_id: item.capability_id,
      name: item.name,
      route_id: item.route_id,
      audience: item.audience,
      purpose: item.purpose,
      prerequisites: item.prerequisites,
      support: item.support,
      limitations: item.limitations,
    }));

  return {
    content: [{
      type: "text" as const,
      text: JSON.stringify({
        service: "beyondquant-mcp",
        status: "ok",
        schema_version: "product-help-result.v1",
        catalog_version: catalog.catalog_version,
        query: request.query,
        matches,
      }),
    }],
    isError: false,
  };
}
