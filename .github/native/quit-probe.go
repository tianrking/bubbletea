package main

import (
	"fmt"
	"os"

	tea "charm.land/bubbletea/v2"
)

type model struct{}

func (model) Init() tea.Cmd { return nil }
func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if key, ok := msg.(tea.KeyPressMsg); ok && key.String() == "q" {
		return m, tea.Quit
	}
	return m, nil
}
func (model) View() tea.View { return tea.NewView("QUIT-LIFECYCLE-READY") }

func main() {
	p := tea.NewProgram(model{}, tea.WithoutSignalHandler())
	fmt.Fprintln(os.Stderr, "QUIT-LIFECYCLE-PRECALL")
	p.Quit()
	fmt.Fprintln(os.Stderr, "QUIT-LIFECYCLE-RETURNED")
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	fmt.Fprintln(os.Stderr, "QUIT-LIFECYCLE-DONE")
}
