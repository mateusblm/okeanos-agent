import { add, subtract, divide, DivisionByZeroError } from "./math.js";
const ops = { add, sub: subtract, div: divide };
const [op, a, b] = process.argv.slice(2);
try {
  console.log(ops[op](Number(a), Number(b)));
} catch (e) {
  if (e instanceof DivisionByZeroError) { console.error(e.message); process.exit(2); }
  throw e;
}
