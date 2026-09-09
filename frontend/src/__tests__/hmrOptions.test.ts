import { describe, expect, it } from "vitest"

import { hmrOptions } from "../../hmrOptions"

describe("hmrOptions", () => {
  it("is undefined without a proxy origin", () => {
    expect(hmrOptions(undefined)).toBeUndefined()
    expect(hmrOptions("")).toBeUndefined()
  })

  it("pins host, scheme and port from an origin carrying a port", () => {
    expect(hmrOptions("https://dojo.localhost:8443")).toEqual({
      protocol: "wss",
      host: "dojo.localhost",
      clientPort: 8443,
    })
  })

  it("omits clientPort when the origin has none, so the page's port is used", () => {
    expect(hmrOptions("https://dojo.localhost")).toEqual({
      protocol: "wss",
      host: "dojo.localhost",
    })
  })

  it("dials ws for a plain-HTTP origin", () => {
    expect(hmrOptions("http://dojo.localhost:8080")).toEqual({
      protocol: "ws",
      host: "dojo.localhost",
      clientPort: 8080,
    })
  })

  it("names the variable when the origin has no scheme", () => {
    expect(() => hmrOptions("dojo.localhost:8443")).toThrow(/DEV_PROXY_ORIGIN/)
  })

  it("names the variable when the origin will not parse", () => {
    expect(() => hmrOptions("https://[")).toThrow(/DEV_PROXY_ORIGIN/)
  })
})
