export class DivisionByZeroError extends Error {}
export const add = (a, b) => a + b;
export const subtract = (a, b) => a - b;
export const divide = (a, b) => {
  if (b === 0) throw new DivisionByZeroError("cannot divide by zero");
  return a / b;
};
