import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DigitKeypad } from "@/components/DigitKeypad";

test("fills six slots, then confirm enables and digits submit", async () => {
  const onConfirm = vi.fn();
  render(<DigitKeypad onConfirm={onConfirm} />);
  const confirm = screen.getByRole("button", { name: "Confirm" });
  expect(confirm).toBeDisabled();
  for (const d of [1, 2, 3, 4, 5, 6]) {
    await userEvent.click(screen.getByRole("button", { name: `digit ${d}` }));
  }
  expect(confirm).toBeEnabled();
  await userEvent.click(confirm);
  expect(onConfirm).toHaveBeenCalledWith([1, 2, 3, 4, 5, 6]);
});

test("clear empties the slots", async () => {
  render(<DigitKeypad />);
  await userEvent.click(screen.getByRole("button", { name: "digit 3" }));
  await userEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(screen.getAllByTestId("slot").every((s) => s.textContent === "—")).toBe(true);
});
