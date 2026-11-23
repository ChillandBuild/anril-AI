"use client";
import { useSettingsForm } from "../SettingsFormContext";
import ConnectChannelsPanel from "./Panel";

export default function ConnectChannelsSettingsPage() {
  const { canManageSettings } = useSettingsForm();
  return <ConnectChannelsPanel canManage={canManageSettings} />;
}
