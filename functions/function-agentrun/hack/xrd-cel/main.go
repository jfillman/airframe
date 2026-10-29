// xrd2crd: print the CRD Crossplane generates for an XRD (crossplane-runtime pkg/xcrd, the code Crossplane v2.3 uses).
package main

import (
	"fmt"
	"os"

	v1 "github.com/crossplane/crossplane/apis/v2/apiextensions/v1"
	v2 "github.com/crossplane/crossplane/apis/v2/apiextensions/v2"
	"github.com/crossplane/crossplane-runtime/v2/pkg/xcrd"
	"sigs.k8s.io/yaml"
)

func main() {
	b, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}
	x2 := &v2.CompositeResourceDefinition{}
	if err := yaml.Unmarshal(b, x2); err != nil {
		panic(err)
	}
	// xcrd takes the v1 type; v2's spec is a superset with the same JSON for what we use.
	x1 := &v1.CompositeResourceDefinition{}
	j, _ := yaml.Marshal(x2)
	if err := yaml.Unmarshal(j, x1); err != nil {
		panic(err)
	}
	crd, err := xcrd.ForCompositeResource(x1)
	if err != nil {
		panic(err)
	}
	crd.APIVersion = "apiextensions.k8s.io/v1"
	crd.Kind = "CustomResourceDefinition"
	out, _ := yaml.Marshal(crd)
	fmt.Print(string(out))
}
