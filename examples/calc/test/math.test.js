import { test } from "node:test";
import assert from "node:assert";
import { subtract, divide, DivisionByZeroError } from "../src/math.js";
test("subtract", () => assert.equal(subtract(5, 3), 2));
test("divide", () => assert.equal(divide(6, 3), 2));
test("divide by zero", () => assert.throws(() => divide(1, 0), DivisionByZeroError));
