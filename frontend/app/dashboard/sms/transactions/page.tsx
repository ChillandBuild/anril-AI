"use client";

import { friendlyError } from "../helpers";
import { BalanceTab } from "../BalanceTab";
import { useSms } from "../SmsShell";

export default function SmsTransactionsPage() {
  const { balance, balanceError, reloadBalance } = useSms();
  return <BalanceTab balance={balance} balanceError={balanceError ? friendlyError(balanceError, "Couldn't load your balance.") : null} onReload={reloadBalance} />;
}
